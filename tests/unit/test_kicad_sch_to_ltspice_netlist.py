"""Unit tests for the KiCad schematic to LTspice netlist conversion API."""  # Describe the unit-test module purpose.

from __future__ import annotations  # Keep annotation handling consistent across the project.

import os  # Read the optional KiCad path environment override.
from pathlib import Path  # Use pathlib for clear path handling.
import tempfile  # Use a temporary directory so tests never modify checked-in netlist files.
import unittest  # Use the standard library test framework.

from electronics_design import is_valid_ltspice_netlist_file  # Import the LTspice netlist whole-file validator.
from electronics_design import kicad_sch_to_ltspice_netlist  # Import the KiCad schematic to LTspice netlist conversion API.

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]  # Resolve the project root from the current test file.
_KICAD_SCH_DIRECTORY = _ROOT_DIRECTORY / "kicad_convert" / "kicad_sch"  # Point at the checked-in KiCad schematic files.
_KICAD_PATH = os.environ.get("ELECTRONICS_DESIGN_KICAD_PATH", "/usr/share/kicad")  # Resolve the KiCad library path with an optional environment override.

_CONVERT_SETTINGS = {  # Pin the settings so generated files are reproducible.
    "kicad_path": _KICAD_PATH,  # Look symbols up from the configured KiCad installation path.
}  # Finish the conversion settings dictionary.


class TestKicadSchToLtspiceNetlist(unittest.TestCase):  # Group the KiCad schematic to LTspice netlist conversion tests together.
    def test_all_kicad_schematics_convert_to_valid_netlists(self) -> None:  # Verify every authoritative KiCad schematic converts to a valid netlist.
        sch_files = sorted(_KICAD_SCH_DIRECTORY.glob("*.kicad_sch"))  # Collect all KiCad schematic files in the fixture directory.
        self.assertGreater(len(sch_files), 0, msg="kicad_convert/kicad_sch/ must contain KiCad schematic files.")  # Require the source files to exist.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch directory for the generated files.
            for sch_path in sch_files:  # Walk every KiCad schematic file.
                with self.subTest(schematic=sch_path.name):  # Isolate failures per schematic file.
                    output_path = Path(temporary_directory) / f"{sch_path.stem}.net"  # Derive the scratch LTspice netlist path.
                    result = kicad_sch_to_ltspice_netlist(str(sch_path), str(output_path), _CONVERT_SETTINGS)  # Run the public conversion API.
                    self.assertEqual(  # Require the conversion to succeed with the standard success tuple.
                        result,  # Compare the returned conversion result.
                        (True, "OK", 0),  # Expect success, the OK message, and line zero.
                        msg=f"{sch_path.name} should convert but returned: {result}",  # Report the failure with the returned tuple.
                    )  # Finish the conversion assertion.
                    validation = is_valid_ltspice_netlist_file(str(output_path))  # Validate the freshly generated netlist file.
                    self.assertEqual(  # Require the generated file to pass the whole-file netlist validator.
                        validation,  # Compare the returned validation result.
                        (True, ""),  # Expect success with an empty message.
                        msg=f"{output_path.name} should be valid but returned: {validation[1]}",  # Report the failure with the returned message.
                    )  # Finish the validation assertion.

    def test_reported_bug_regressions(self) -> None:  # Verify topology, source, directive, and power-name bugs stay fixed.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Keep all generated regression outputs outside the fixture tree.
            generated: dict[str, list[str]] = {}  # Collect generated lines by schematic stem.
            for stem in ("rc-filter", "Boost2", "555bip", "ICL8038"):  # Convert every fixture cited by BUGS.md.
                output_path = Path(temporary_directory) / f"{stem}.net"  # Derive a scratch output path.
                result = kicad_sch_to_ltspice_netlist(str(_KICAD_SCH_DIRECTORY / f"{stem}.kicad_sch"), str(output_path), _CONVERT_SETTINGS)  # Convert the authoritative KiCad schematic.
                self.assertEqual(result, (True, "OK", 0), msg=f"{stem} regression conversion failed: {result}")  # Require a usable generated deck.
                generated[stem] = output_path.read_text(encoding="utf-8").splitlines()  # Read the generated netlist for focused assertions.

            rc_lines = generated["rc-filter"]  # Read the sinusoidal-source and power-symbol fixture.
            self.assertIn("V1 VDD 0 SINE(2 1 1k 0 0 0) AC 1", rc_lines)  # Preserve the full VSIN Sim.Params payload.
            rc_instance_names = [line.split()[0].upper() for line in rc_lines if line and not line.startswith(("*", "."))]  # Collect emitted device names while excluding comments and directives.
            self.assertEqual(len(rc_instance_names), len(set(rc_instance_names)), msg="Power-derived sources must not collide with real component names.")  # Require globally unique instance names.
            self.assertTrue(any(line.startswith("V_PWR02 VDD 0 VDD") for line in rc_lines), msg="The VDD power symbol must use a reference-derived valid source name.")  # Preserve the power source without reusing V1.

            boost_lines = generated["Boost2"]  # Read the pulse-source and multiline-directive fixture.
            self.assertIn("V3 in 0 PULSE(0 2.5 0 0.5m 0.5m 1 2)", boost_lines)  # Preserve the first VPULSE payload.
            self.assertIn("V1 gg 0 PULSE(0 10 0 20n 20n {ducyc/freq} {1/freq})", boost_lines)  # Preserve parameter expressions in the second pulse source.
            self.assertIn(".options chgtol=1e-11 abstol=10u", boost_lines)  # Preserve the first schematic directive line.
            self.assertIn(".param freq=1Meg ducyc=0.6", boost_lines)  # Preserve the second schematic directive line.

            bipolar_lines = generated["555bip"]  # Read the mirrored-transistor fixture.
            q16_line = next(line for line in bipolar_lines if line.startswith("Q16 "))  # Locate the specifically reported mirrored transistor.
            self.assertNotIn("NC_", q16_line, msg="Every physically wired Q16 pin must resolve through the mirrored pin geometry.")  # Reject the former disconnected nodes.
            self.assertIn(".tran 1u 12m", bipolar_lines)  # Preserve the schematic's requested transient analysis.
            self.assertNotIn(".tran 1", bipolar_lines)  # Do not add the fallback when an analysis already exists.

            icl_lines = generated["ICL8038"]  # Read the endpoint-contact and dangling-wire fixture.
            v2_line = next(line for line in icl_lines if line.startswith("V2 "))  # Locate the reported voltage source.
            r27_line = next(line for line in icl_lines if line.startswith("R27 "))  # Locate the reported rotated resistor.
            self.assertEqual(v2_line, "V2 Pin6 0 10")  # Join the source pin through its wire to the Pin6 global label.
            self.assertFalse(r27_line.split()[1].upper().startswith("NC"), msg="A resistor pin touching a physical wire must not become an NC node.")  # Preserve physical dangling copper as a wired node.

    def test_bugs_md_ground_truth_regressions(self) -> None:  # Cover every converter defect independently verified against KiCad's exporter.
        stems = (  # Select the smallest fixture set that exercises all eight reported bug classes.
            "LLC2",  # Quarter-turn directional pin geometry.
            "QEI",  # Multi-unit package merging.
            "rel_osc",  # Multi-unit gate and power-pin merging.
            "generic_opamp_bip",  # Subcircuit parameters and configured KiCad library expansion.
            "Q17ng",  # Generic SPICE passives, explicit model names, and model libraries.
            "a-multi",  # Legacy SPICE_Basic resistor primitive/value recovery.
            "royer1",  # Mutual-inductance statements.
            "ibis2",  # Transmission-line parameters.
            "pulse-generator-sim",  # Uppercase-M mega normalization and multi-unit merging.
            "LM3886_Tian",  # Sim.Pins filtering for a package with unused pins.
            "741",  # Semiconductor model library preservation.
            "smps-com",  # Duplicate reference renumbering.
        )  # Finish the regression fixture list.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Generate every deck outside the checked-in fixture directories.
            generated: dict[str, list[str]] = {}  # Collect emitted lines by schematic name.
            for stem in stems:  # Convert each authoritative schematic.
                output_path = Path(temporary_directory) / f"{stem}.net"  # Derive its temporary output path.
                result = kicad_sch_to_ltspice_netlist(str(_KICAD_SCH_DIRECTORY / f"{stem}.kicad_sch"), str(output_path), _CONVERT_SETTINGS)  # Run the public converter.
                self.assertEqual(result, (True, "OK", 0), msg=f"{stem} BUGS.md regression conversion failed: {result}")  # Require a valid generated deck.
                generated[stem] = output_path.read_text(encoding="utf-8").splitlines()  # Read the deck for focused checks.

            d2_tokens = next(line.split() for line in generated["LLC2"] if line.startswith("D2 "))  # Locate the rotated diode independently of its valid model alias.
            self.assertEqual(d2_tokens[1:3], ["N005", "out"])  # Keep the rotated diode anode on the transformer node and cathode on out.
            qei_u1 = [line for line in generated["QEI"] if line.startswith("XU1 ")]  # Locate the merged dual flip-flop call.
            self.assertEqual(len(qei_u1), 1, msg="Distinct U1 units must emit one physical subcircuit instance.")  # Reject duplicate partial instances.
            self.assertEqual(len(qei_u1[0].split()) - 2, 14, msg="The merged 74HC74 call must carry all fourteen package ports.")  # Exclude instance and model tokens from the node count.
            rel_u1 = [line for line in generated["rel_osc"] if line.startswith("XU1 ")]  # Locate the merged hex-inverter package.
            self.assertEqual(rel_u1, ["XU1 cc out 0 vdd CD40106B"])  # Merge its gate and supply units into KiCad's four-port simulation model.
            generic_u1 = next(line for line in generated["generic_opamp_bip"] if line.startswith("XU1 "))  # Locate the built-in op-amp call.
            self.assertTrue(generic_u1.endswith("kicad_builtin_opamp POLE=30 GAIN=100k VOFF=10u ROUT=10"))  # Preserve true subcircuit instance parameters.

            self.assertIn("C4 0 v+ 100n", generated["Q17ng"])  # Recover a generic SPICE capacitor as a C primitive with its model value.
            self.assertIn("R1 out 0 1k", generated["a-multi"])  # Recover the legacy SPICE_Basic resistor primitive and Spice_Model value.
            self.assertEqual([line for line in generated["royer1"] if line.startswith("K")], [  # Preserve every coupled-inductor statement in source order.
                "K1 L1 L2 0.98", "K2 L1 L3 0.98", "K3 L1 l4 0.98", "K4 L2 L3 0.98", "K5 L2 L4 0.98", "K6 L3 L4 0.98",
            ])  # Finish the mutual-inductance assertion.
            self.assertIn("T1 out1 0 in2 0 Zo=50 Td=1n", generated["ibis2"])  # Carry lossless transmission-line impedance and delay.
            self.assertIn("R5 an AOUT 1Meg", generated["pulse-generator-sim"])  # Prevent uppercase M from becoming SPICE milli.
            lm3886_u1 = next(line for line in generated["LM3886_Tian"] if line.startswith("XU1 "))  # Locate the audio-amplifier subcircuit.
            self.assertEqual(len(lm3886_u1.split()) - 2, 6, msg="Sim.Pins must omit package pins absent from the LM3886 model.")  # Match KiCad's six model ports.

            self.assertIn('.include "bipmod.lib"', generated["741"])  # Preserve the library that defines PN/NP transistor models.
            self.assertIn('.include "all_devices.lib"', generated["Q17ng"])  # Preserve the model source used by Q17ng semiconductors.
            self.assertTrue(any(line.startswith("Q7 ") and line.endswith(" Q2SC2240") for line in generated["Q17ng"]))  # Prefer Sim.Name over the display value for model lookup.
            smps_names = [line.split()[0].upper() for line in generated["smps-com"] if line and not line.startswith(("*", "."))]  # Collect all emitted smps-com instance names.
            self.assertEqual(len(smps_names), len(set(smps_names)), msg="Unannotated duplicate references must be deterministically renumbered.")  # Require a valid unique instance namespace.

    def test_missing_input_returns_invalid_kicad_sch_file(self) -> None:  # Verify the missing input error contract.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch directory for the call.
            result = kicad_sch_to_ltspice_netlist(  # Call the conversion API with a nonexistent input.
                str(_KICAD_SCH_DIRECTORY / "does_not_exist.kicad_sch"),  # Use a path that cannot exist.
                str(Path(temporary_directory) / "does_not_exist.net"),  # Use a writable output path.
                _CONVERT_SETTINGS,  # Pass the shared settings mapping.
            )  # Finish the conversion call.
            self.assertEqual(result[0], False, msg="Missing input files must fail conversion.")  # Require failure.
            self.assertEqual(result[1], "INVALID_KICAD_SCH_FILE", msg="Missing input files must report the schematic error code.")  # Require the schematic error code.
            self.assertEqual(result[2], 0, msg="Path failures must report line zero.")  # Require the unknown line number.

    def test_invalid_settings_return_invalid_convert_settings(self) -> None:  # Verify the settings validation error contract.
        source_path = next(_KICAD_SCH_DIRECTORY.glob("*.kicad_sch"))  # Read one valid source file for the call.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch directory for the call.
            result = kicad_sch_to_ltspice_netlist(  # Call the conversion API with invalid settings.
                str(source_path),  # Pass the valid source path.
                str(Path(temporary_directory) / "ignored.net"),  # Pass a writable output path.
                "not a mapping",  # Pass a non-mapping settings value.
            )  # Finish the conversion call.
            self.assertEqual(result, (False, "INVALID_CONVERT_SETTINGS", 0), msg="Non-mapping settings must fail with the settings error code.")  # Require the settings error tuple.

    def test_missing_kicad_path_returns_invalid_convert_settings(self) -> None:  # Verify that a missing kicad_path setting is rejected.
        source_path = next(_KICAD_SCH_DIRECTORY.glob("*.kicad_sch"))  # Read one valid source file for the call.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch directory for the call.
            result = kicad_sch_to_ltspice_netlist(  # Call the conversion API without the kicad_path setting.
                str(source_path),  # Pass the valid source path.
                str(Path(temporary_directory) / "ignored.net"),  # Pass a writable output path.
                {"kicad_path": str(Path(temporary_directory) / "missing_kicad")},  # Pass a kicad_path that does not exist.
            )  # Finish the conversion call.
            self.assertEqual(result, (False, "INVALID_CONVERT_SETTINGS", 0), msg="Missing kicad_path directories must fail with the settings error code.")  # Require the settings error tuple.

    def test_invalid_output_path_returns_invalid_output_path(self) -> None:  # Verify the output path error contract.
        source_path = next(_KICAD_SCH_DIRECTORY.glob("*.kicad_sch"))  # Read one valid source file for the call.
        result = kicad_sch_to_ltspice_netlist(  # Call the conversion API with a non-path output.
            str(source_path),  # Pass the valid source path.
            12345,  # Pass a non-path-like output value.
            _CONVERT_SETTINGS,  # Pass the shared settings mapping.
        )  # Finish the conversion call.
        self.assertEqual(result, (False, "INVALID_OUTPUT_PATH", 0), msg="Non-path outputs must fail with the output path error code.")  # Require the output path error tuple.

    def test_unknown_symbol_returns_unknown_kicad_symbol(self) -> None:  # Verify that unresolved symbols report the unknown symbol error.
        source_path = next(  # Select a fixture that the tampering operation can actually modify.
            candidate_path
            for candidate_path in sorted(_KICAD_SCH_DIRECTORY.glob("*.kicad_sch"))
            if '(lib_id "Device:R")' in candidate_path.read_text(encoding="utf-8")
        )  # Finish selecting a deterministic resistor-bearing schematic.
        source_text = source_path.read_text(encoding="utf-8")  # Read the schematic text.
        tampered_text = source_text.replace('(lib_id "Device:R")', '(lib_id "NonexistentLibrary:R")')  # Break every resistor instance library reference.
        with tempfile.TemporaryDirectory() as temporary_directory:  # Create a scratch directory for the tampered input and output.
            tampered_path = Path(temporary_directory) / "tampered.kicad_sch"  # Derive the tampered schematic path.
            tampered_path.write_text(tampered_text, encoding="utf-8")  # Write the tampered schematic.
            result = kicad_sch_to_ltspice_netlist(  # Call the conversion API on the tampered schematic.
                str(tampered_path),  # Pass the tampered schematic path.
                str(Path(temporary_directory) / "tampered.net"),  # Pass a writable output path.
                _CONVERT_SETTINGS,  # Pass the shared settings mapping.
            )  # Finish the conversion call.
            self.assertEqual(result[0], False, msg="Unresolvable symbols must fail conversion.")  # Require failure.
            self.assertTrue(result[1].startswith("UNKNOWN_KICAD_SYMBOL"), msg=f"Unresolvable symbols must report UNKNOWN_KICAD_SYMBOL but returned: {result[1]}")  # Require the symbol error code.
            self.assertGreater(result[2], 0, msg="Symbol failures must report the instance source line.")  # Require a real line number.


if __name__ == "__main__":  # Allow running the module directly for debugging.
    unittest.main()  # Execute the unit tests when invoked as a script.
