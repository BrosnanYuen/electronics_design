"""Unit tests for supporting LTspice symbol pose estimation."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from electronics_design import ltspice_symbol_estimate
from electronics_design import ltspice_symbol_facing

_ROOT_DIRECTORY = Path(__file__).resolve().parents[2]
_FIXTURE_DIRECTORY = _ROOT_DIRECTORY / "test_files" / "symbol_pose_test"
_CONVERT_SETTINGS = {
    "ltspice_windows_path": "C:\\users\\brosnan\\AppData\\Local\\LTspice\\",
    "ltspice_wine_path": "~/.wine/drive_c/users/brosnan/AppData/Local/LTspice/",
    "custom_search_paths": ["./valid_asy/"],
    "minimum_dist": 48,
    "wire_pin_out_dist": 16,
    "autoplace_iter": 12,
    "grid_size": 16,
    "ltspice_version": 4.1,
    "voltage_must_have_dc": False,
}
_OPPOSITE_DIRECTION = {
    "+X DIRECTION": "-X DIRECTION",
    "-X DIRECTION": "+X DIRECTION",
    "+Y DIRECTION": "-Y DIRECTION",
    "-Y DIRECTION": "+Y DIRECTION",
}
_SCENARIOS = {
    "case_01.json": {
        "args": ("M1", 1, "R1", 1),
        "expected": {
            "R1": {
                "SYMBOL": "res",
                "X": 512,
                "Y": 368,
                "ORIENTATION": "R0",
                "RECTANGLE": [[512, 384], [544, 464]],
                "PINS": [[528, 384, "A", 1], [528, 464, "B", 2]],
            }
        },
    },
    "case_02.json": {
        "args": ("M2", 3, "C1", 1),
        "expected": {
            "C1": {
                "SYMBOL": "cap",
                "X": 224,
                "Y": 224,
                "ORIENTATION": "R90",
                "RECTANGLE": [[160, 224], [224, 256]],
                "PINS": [[224, 240, "A", 1], [160, 240, "B", 2]],
            }
        },
    },
    "case_03.json": {
        "args": ("U1", 5, "R1", 1),
        "expected": {
            "R1": {
                "SYMBOL": "res",
                "X": 400,
                "Y": 304,
                "ORIENTATION": "R270",
                "RECTANGLE": [[416, 272], [496, 304]],
                "PINS": [[416, 288, "A", 1], [496, 288, "B", 2]],
            }
        },
    },
    "case_04.json": {
        "args": ("U1", 1, "C1", 1),
        "expected": {
            "C1": {
                "SYMBOL": "cap",
                "X": 448,
                "Y": 336,
                "ORIENTATION": "R90",
                "RECTANGLE": [[384, 336], [448, 368]],
                "PINS": [[448, 352, "A", 1], [384, 352, "B", 2]],
            }
        },
    },
    "case_05.json": {
        "args": ("U1", 4, "L1", 1),
        "expected": {
            "L1": {
                "SYMBOL": "ind",
                "X": 384,
                "Y": 256,
                "ORIENTATION": "R0",
                "RECTANGLE": [[384, 272], [416, 352]],
                "PINS": [[400, 272, "A", 1], [400, 352, "B", 2]],
            }
        },
    },
    "case_06.json": {
        "args": ("U1", 5, "C1", 2),
        "expected": {
            "C1": {
                "SYMBOL": "cap",
                "X": 208,
                "Y": 560,
                "ORIENTATION": "R180",
                "RECTANGLE": [[176, 496], [208, 560]],
                "PINS": [[192, 560, "A", 1], [192, 496, "B", 2]],
            }
        },
    },
    "case_07.json": {
        "args": ("U1", 4, "L1", 2),
        "expected": {
            "L1": {
                "SYMBOL": "ind",
                "X": 112,
                "Y": 352,
                "ORIENTATION": "R270",
                "RECTANGLE": [[128, 320], [208, 352]],
                "PINS": [[128, 336, "A", 1], [208, 336, "B", 2]],
            }
        },
    },
    "case_08.json": {
        "args": ("U1", 3, "R1", 2),
        "expected": {
            "R1": {
                "SYMBOL": "res",
                "X": 320,
                "Y": 224,
                "ORIENTATION": "R90",
                "RECTANGLE": [[224, 224], [304, 256]],
                "PINS": [[304, 240, "A", 1], [224, 240, "B", 2]],
            }
        },
    },
    "case_09.json": {
        "args": ("U1", 5, "L1", 1),
        "expected": {
            "L1": {
                "SYMBOL": "ind",
                "X": 240,
                "Y": 224,
                "ORIENTATION": "R90",
                "RECTANGLE": [[144, 224], [224, 256]],
                "PINS": [[224, 240, "A", 1], [144, 240, "B", 2]],
            }
        },
    },
    "case_10.json": {
        "args": ("U1", 3, "R1", 1),
        "expected": {
            "R1": {
                "SYMBOL": "res",
                "X": 528,
                "Y": 192,
                "ORIENTATION": "R0",
                "RECTANGLE": [[528, 208], [560, 288]],
                "PINS": [[544, 208, "A", 1], [544, 288, "B", 2]],
            }
        },
    },
    "case_11.json": {
        "args": ("U1", 4, "C1", 2),
        "expected": {
            "C1": {
                "SYMBOL": "cap",
                "X": 352,
                "Y": 192,
                "ORIENTATION": "R0",
                "RECTANGLE": [[352, 192], [384, 256]],
                "PINS": [[368, 192, "A", 1], [368, 256, "B", 2]],
            }
        },
    },
    "case_12.json": {
        "args": ("U1", 5, "L1", 2),
        "expected": {
            "L1": {
                "SYMBOL": "ind",
                "X": 272,
                "Y": 0,
                "ORIENTATION": "R0",
                "RECTANGLE": [[272, 16], [304, 96]],
                "PINS": [[288, 16, "A", 1], [288, 96, "B", 2]],
            }
        },
    },
    "case_13.json": {
        "args": ("U1", 3, "C1", 1),
        "expected": {
            "C1": {
                "SYMBOL": "cap",
                "X": 480,
                "Y": 336,
                "ORIENTATION": "R90",
                "RECTANGLE": [[416, 336], [480, 368]],
                "PINS": [[480, 352, "A", 1], [416, 352, "B", 2]],
            }
        },
    },
    "case_14.json": {
        "args": ("U1", 4, "R1", 2),
        "expected": {
            "R1": {
                "SYMBOL": "res",
                "X": 880,
                "Y": 272,
                "ORIENTATION": "R90",
                "RECTANGLE": [[784, 272], [864, 304]],
                "PINS": [[864, 288, "A", 1], [784, 288, "B", 2]],
            }
        },
    },
    "case_15.json": {
        "args": ("U1", 1, "L1", 1),
        "expected": {
            "L1": {
                "SYMBOL": "ind",
                "X": 496,
                "Y": 576,
                "ORIENTATION": "R0",
                "RECTANGLE": [[496, 592], [528, 672]],
                "PINS": [[512, 592, "A", 1], [512, 672, "B", 2]],
            }
        },
    },
}


def _parse_rectangle(rectangle_points: list[list[int]]) -> tuple[int, int, int, int]:
    return (
        min(int(rectangle_points[0][0]), int(rectangle_points[1][0])),
        min(int(rectangle_points[0][1]), int(rectangle_points[1][1])),
        max(int(rectangle_points[0][0]), int(rectangle_points[1][0])),
        max(int(rectangle_points[0][1]), int(rectangle_points[1][1])),
    )


def _find_pin_direction(rows: list[list[object]], spice_order: int) -> tuple[int, int, str]:
    for raw_row in rows:
        if int(raw_row[3]) == spice_order:
            return int(raw_row[0]), int(raw_row[1]), str(raw_row[4])
    raise AssertionError(f"Missing pin id {spice_order} in symbol facing rows")


class TestLtspiceSymbolEstimate(unittest.TestCase):
    def test_all_symbol_estimate_fixtures(self) -> None:
        fixture_paths = sorted(_FIXTURE_DIRECTORY.glob("*.json"))
        self.assertEqual(
            [fixture_path.name for fixture_path in fixture_paths],
            sorted(_SCENARIOS),
            msg="The symbol-estimate fixture set on disk should match the expected scenario map exactly.",
        )
        for fixture_path in fixture_paths:
            scenario = _SCENARIOS[fixture_path.name]
            core_symbol_name, core_symbol_pin_id, supporting_symbol_name, supporting_symbol_pin_id = scenario["args"]
            input_payload = json.loads(fixture_path.read_text(encoding="utf-8"))
            expected_output = scenario["expected"]
            with self.subTest(fixture=fixture_path.name):
                result = ltspice_symbol_estimate(
                    str(fixture_path),
                    core_symbol_name,
                    core_symbol_pin_id,
                    supporting_symbol_name,
                    supporting_symbol_pin_id,
                    _CONVERT_SETTINGS,
                )
                self.assertEqual(result, expected_output, msg=f"{fixture_path.name} should match the expected estimated symbol pose exactly.")
                self.assertIn(
                    result[supporting_symbol_name]["ORIENTATION"],
                    {"R0", "R90", "R180", "R270"},
                    msg=f"{fixture_path.name} should only emit non-mirrored supporting symbol orientations.",
                )
                core_rectangle = _parse_rectangle(input_payload[core_symbol_name]["RECTANGLE"])
                support_rectangle = _parse_rectangle(result[supporting_symbol_name]["RECTANGLE"])
                self.assertFalse(
                    max(core_rectangle[0], support_rectangle[0]) < min(core_rectangle[2], support_rectangle[2])
                    and max(core_rectangle[1], support_rectangle[1]) < min(core_rectangle[3], support_rectangle[3]),
                    msg=f"{fixture_path.name} should not collide with the fixed core symbol.",
                )
                with tempfile.TemporaryDirectory() as temporary_directory:
                    working_path = Path(temporary_directory) / fixture_path.name
                    merged_payload = dict(input_payload)
                    merged_payload.update(result)
                    working_path.write_text(json.dumps(merged_payload, indent=2) + "\n", encoding="utf-8")
                    facing_map = ltspice_symbol_facing(str(working_path), _CONVERT_SETTINGS)
                core_pin_x, core_pin_y, core_direction = _find_pin_direction(facing_map[core_symbol_name], core_symbol_pin_id)
                support_pin_x, support_pin_y, support_direction = _find_pin_direction(
                    facing_map[supporting_symbol_name],
                    supporting_symbol_pin_id,
                )
                self.assertEqual(
                    support_direction,
                    _OPPOSITE_DIRECTION[core_direction],
                    msg=f"{fixture_path.name} should make the supporting symbol pin face opposite the core symbol pin.",
                )
                if core_direction in {"+X DIRECTION", "-X DIRECTION"}:
                    self.assertEqual(
                        core_pin_y,
                        support_pin_y,
                        msg=f"{fixture_path.name} should place the two connected pins on a straight horizontal line.",
                    )
                    horizontal_gap = support_rectangle[0] - core_rectangle[2] if core_direction == "+X DIRECTION" else core_rectangle[0] - support_rectangle[2]
                    self.assertEqual(
                        horizontal_gap,
                        _CONVERT_SETTINGS["minimum_dist"],
                        msg=f"{fixture_path.name} should place the supporting symbol exactly minimum_dist away along the horizontal connection axis.",
                    )
                else:
                    self.assertEqual(
                        core_pin_x,
                        support_pin_x,
                        msg=f"{fixture_path.name} should place the two connected pins on a straight vertical line.",
                    )
                    vertical_gap = support_rectangle[1] - core_rectangle[3] if core_direction == "+Y DIRECTION" else core_rectangle[1] - support_rectangle[3]
                    self.assertEqual(
                        vertical_gap,
                        _CONVERT_SETTINGS["minimum_dist"],
                        msg=f"{fixture_path.name} should place the supporting symbol exactly minimum_dist away along the vertical connection axis.",
                    )
