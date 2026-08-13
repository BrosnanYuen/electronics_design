"""Vendored KiCad S-expression parser core for schematic validation."""  # Describe the vendored parser module purpose.

# This module is a trimmed copy of the S-expression parser shipped by the
# `kicad-tools` project (https://github.com/rintarooo/kicad-tools),
# `src/kicad_tools/sexp/parser.py`, which is distributed under the MIT license:
#
#   MIT License
#   Copyright (c) 2024 RJ Walters
#   Permission is hereby granted, free of charge, to any person obtaining a
#   copy of this software and associated documentation files (the "Software"),
#   to deal in the Software without restriction, including without limitation
#   the rights to use, copy, modify, merge, publish, distribute, sublicense,
#   and/or sell copies of the Software ... (see the full license text in the
#   kicad-tools repository).
#
# Only the read-side pieces needed for `.kicad_sch` validation are kept: the
# `SExp` node type, the `Parser`, `ParseError`, and `parse_string`. The
# serializer, XPath-style query helpers, and `Document` file API are omitted.
# Two local adaptations were made:
#   * `ParseError` carries the failing byte offset (`ParseError.pos`) so the
#     public validators can report a source line number.
#   * `parse_string` drops the file-path guard because this package only ever
#     feeds the parser validated file text.

from __future__ import annotations  # Postpone annotation evaluation for forward references.

from typing import Any  # Type the generic SExp attribute matcher.
from typing import List  # Type parsed child lists.
from typing import Optional  # Type optional SExp fields.
from typing import Tuple  # Type parser position tuples.

_WHITESPACE = frozenset(" \t\n\r")  # Precompute whitespace characters for fast membership checks.
_ATOM_TERMINATORS = frozenset(" \t\n\r()")  # Precompute characters that terminate an unquoted atom.
_COMMENT_CHARS = frozenset("#;")  # Precompute characters that begin a line comment.
_ESCAPE_MAP = {"n": "\n", "t": "\t", "r": "\r"}  # Map supported escape characters to their decoded values.


class SExp:  # Represent one parsed S-expression node.
    """S-expression node: a named list, an empty list, or an atom value.

    Position tracking: when parsed with `track_positions=True`, nodes include
    one-based `_line` and `_column` attributes pointing at their start in the
    source text. Atoms parsed from quoted strings set `_originally_quoted`;
    atoms parsed from bare tokens set `_originally_bare`.
    """

    __slots__ = (  # Limit per-node memory for fast parsing of large KiCad files.
        "name",  # Store the list name for named list nodes.
        "children",  # Store child nodes for list nodes.
        "value",  # Store the atom value for atom nodes.
        "_inline",  # Reserve the serializer inline flag for compatibility.
        "_original_str",  # Preserve the source spelling of numeric atoms.
        "_originally_quoted",  # Record whether a string atom was quoted in the source.
        "_originally_bare",  # Record whether a string atom was bare in the source.
        "_line",  # Store the one-based source line for position tracking.
        "_column",  # Store the one-based source column for position tracking.
    )

    def __init__(  # Construct one S-expression node.
        self,  # Bind the node being constructed.
        name: Optional[str] = None,  # Accept an optional list name.
        children: Optional[List["SExp"]] = None,  # Accept optional child nodes.
        value: Optional[Any] = None,  # Accept an optional atom value.
        _inline: bool = False,  # Accept the serializer inline flag.
        _original_str: Optional[str] = None,  # Accept the numeric source spelling.
        _originally_quoted: bool = False,  # Accept the quoted-atom marker.
        _originally_bare: bool = False,  # Accept the bare-atom marker.
        _line: int = 0,  # Accept the one-based source line.
        _column: int = 0,  # Accept the one-based source column.
    ) -> None:
        if name is not None and value is not None:  # Reject nodes that would be both lists and atoms.
            raise ValueError("SExp cannot have both name and value")  # Raise for the ambiguous node shape.
        self.name = name  # Store the list name.
        self.children = children if children is not None else []  # Store the child list.
        self.value = value  # Store the atom value.
        self._inline = _inline  # Store the inline flag.
        self._original_str = _original_str  # Store the numeric source spelling.
        self._originally_quoted = _originally_quoted  # Store the quoted-atom marker.
        self._originally_bare = _originally_bare  # Store the bare-atom marker.
        self._line = _line  # Store the source line.
        self._column = _column  # Store the source column.

    @property  # Expose the source line as a read-only property.
    def line(self) -> int:  # Return the one-based source line of this node.
        return self._line  # Return zero when position tracking was disabled.

    @property  # Expose the source column as a read-only property.
    def column(self) -> int:  # Return the one-based source column of this node.
        return self._column  # Return zero when position tracking was disabled.

    @property  # Expose position availability as a read-only property.
    def has_position(self) -> bool:  # Return whether the node carries a source position.
        return self._line > 0 and self._column > 0  # Both coordinates must be nonzero.

    @property  # Expose atom classification as a read-only property.
    def is_atom(self) -> bool:  # Return whether the node is a leaf atom.
        return self.name is None and not self.children  # Atoms have neither a name nor children.

    @property  # Expose list classification as a read-only property.
    def is_list(self) -> bool:  # Return whether the node is a list.
        return self.name is not None or bool(self.children)  # Lists have a name or children.

    def find_child(self, tag: str) -> Optional["SExp"]:  # Find the first direct child with the given tag.
        for child in self.children:  # Walk the direct children only.
            if child.name == tag:  # Match children by exact list name.
                return child  # Return the first matching direct child.
        return None  # Return None when no direct child matches.

    def find_children(self, tag: str) -> List["SExp"]:  # Find all direct children with the given tag.
        return [child for child in self.children if child.name == tag]  # Collect every matching direct child.

    def get(self, tag: str, default: Optional["SExp"] = None) -> Optional["SExp"]:  # Fetch a direct child or a default.
        for child in self.children:  # Walk the direct children only.
            if child.name == tag:  # Match children by exact list name.
                return child  # Return the first matching direct child.
        return default  # Return the supplied default when nothing matches.


class ParseError(ValueError):  # Represent an S-expression syntax failure.
    """Error during S-expression parsing.

    Inherits from ValueError so callers can treat parsing failures with
    ordinary exception handling. The `pos` attribute holds the failing byte
    offset in the source text (local adaptation over kicad-tools).
    """

    def __init__(self, message: str, pos: int = 0):  # Build the parse error with an optional failing offset.
        super().__init__(message)  # Store the human-readable parse message.
        self.pos = pos  # Store the failing byte offset for line-number reporting.


class Parser:  # Parse KiCad S-expression text into an SExp tree.
    """S-expression parser for KiCad files.

    Position tracking: when `track_positions=True`, parsed nodes include
    one-based line and column information for error reporting.
    """

    __slots__ = ("text", "pos", "length", "_track_positions", "_line_starts")  # Bound parser state to these slots.

    def __init__(self, text: str, track_positions: bool = False) -> None:  # Construct a parser over one source text.
        self.text = text  # Store the full source text.
        self.pos = 0  # Start the read cursor at the beginning.
        self.length = len(text)  # Cache the source length for hot-path checks.
        self._track_positions = track_positions  # Store the position-tracking switch.
        if track_positions:  # Precompute line-start offsets only when positions are requested.
            self._line_starts = [0]  # Start the line map with the offset of line one.
            for index, char in enumerate(text):  # Walk every character to locate newlines.
                if char == "\n":  # Detect a newline character.
                    self._line_starts.append(index + 1)  # Record the offset where the next line begins.
        else:  # Skip the line map when positions are not needed.
            self._line_starts = []  # Store an empty line map.

    def _get_position(self, pos: int) -> Tuple[int, int]:  # Convert a byte offset into a one-based line and column.
        if not self._track_positions:  # Short-circuit when position tracking is disabled.
            return (0, 0)  # Return the neutral untracked position.
        line_starts = self._line_starts  # Alias the precomputed line map.
        lo, hi = 0, len(line_starts)  # Initialize the binary search bounds.
        while lo < hi:  # Binary search for the line containing the offset.
            mid = (lo + hi) // 2  # Compute the search midpoint.
            if line_starts[mid] <= pos:  # Decide whether the offset is past the midpoint line.
                lo = mid + 1  # Move the lower bound past the midpoint.
            else:  # The offset is at or before the midpoint line.
                hi = mid  # Move the upper bound to the midpoint.
        line = lo  # Derive the one-based line number from the search result.
        column = pos - line_starts[line - 1] + 1  # Derive the one-based column from the line start.
        return (line, column)  # Return the resolved source position.

    def parse(self) -> SExp:  # Parse the entire document into one S-expression.
        self._skip_whitespace()  # Skip leading whitespace and comments.
        result = self._parse_expr()  # Parse the first expression.
        self._skip_whitespace()  # Skip any trailing whitespace and comments.
        if self.pos < self.length:  # Reject trailing content after the first expression.
            raise ParseError(f"Unexpected content at position {self.pos}", self.pos)  # Raise with the failing offset.
        return result  # Return the parsed expression tree.

    def _parse_expr(self) -> SExp:  # Parse one S-expression node.
        text = self.text  # Alias the source text for hot-path speed.
        length = self.length  # Alias the source length for hot-path speed.
        pos = self.pos  # Alias the read cursor.
        while pos < length and text[pos] in _WHITESPACE:  # Skip inline whitespace.
            pos += 1  # Advance past the whitespace character.
        while pos < length and text[pos] in _COMMENT_CHARS:  # Skip comment lines.
            while pos < length and text[pos] != "\n":  # Skip to the end of the comment line.
                pos += 1  # Advance through the comment text.
            while pos < length and text[pos] in _WHITESPACE:  # Skip whitespace after the comment.
                pos += 1  # Advance past the whitespace character.
        self.pos = pos  # Commit the cursor after whitespace and comments.
        if pos >= length:  # Reject input that ends before an expression appears.
            raise ParseError("Unexpected end of input", pos)  # Raise with the end-of-input offset.
        start_pos = pos  # Record the node start for position tracking.
        char = text[pos]  # Inspect the character that begins the node.
        if char == "(":  # Parse a parenthesized list.
            node = self._parse_list()  # Delegate to the list parser.
        elif char == '"':  # Parse a quoted string atom.
            node = self._parse_string_node()  # Delegate to the string parser.
        else:  # Parse a bare atom.
            node = self._parse_atom()  # Delegate to the atom parser.
        if self._track_positions:  # Attach source positions only when requested.
            line, column = self._get_position(start_pos)  # Resolve the node start position.
            node._line = line  # Store the resolved line.
            node._column = column  # Store the resolved column.
        return node  # Return the parsed node.

    def _parse_list(self) -> SExp:  # Parse a parenthesized list node.
        text = self.text  # Alias the source text for hot-path speed.
        length = self.length  # Alias the source length for hot-path speed.
        self.pos += 1  # Skip the opening parenthesis.
        pos = self.pos  # Alias the cursor after the opening parenthesis.
        while pos < length and text[pos] in _WHITESPACE:  # Skip whitespace inside the list.
            pos += 1  # Advance past the whitespace character.
        while pos < length and text[pos] in _COMMENT_CHARS:  # Skip comment lines inside the list.
            while pos < length and text[pos] != "\n":  # Skip to the end of the comment line.
                pos += 1  # Advance through the comment text.
            while pos < length and text[pos] in _WHITESPACE:  # Skip whitespace after the comment.
                pos += 1  # Advance past the whitespace character.
        self.pos = pos  # Commit the cursor before reading the list head.
        if pos >= length:  # Reject lists that end before closing.
            raise ParseError("Unexpected end of input in list", pos)  # Raise with the end-of-input offset.
        char = text[pos]  # Inspect the character that begins the list.
        if char == ")":  # Handle the empty-list case.
            self.pos = pos + 1  # Consume the closing parenthesis.
            return SExp()  # Return an anonymous empty list.
        if char != "(" and char != '"':  # Fast path: parse an unquoted token as the list head.
            start = pos  # Record the head token start.
            while pos < length and text[pos] not in _ATOM_TERMINATORS:  # Scan to the end of the token.
                pos += 1  # Advance through the token characters.
            self.pos = pos  # Commit the cursor after the head token.
            if pos > start:  # Require at least one head token character.
                token = text[start:pos]  # Extract the head token text.
                if token and not token[0].isdigit() and token[0] != "-":  # Treat identifier heads as list names.
                    node = SExp(name=token)  # Create a named list node.
                else:  # Numeric or sign-leading heads still become list names.
                    first_char = token[0]  # Inspect the head token start.
                    if first_char.isdigit() or (first_char == "-" and len(token) > 1):  # Accept numeric list heads.
                        node = SExp(name=token)  # Create a named list node for numeric heads.
                    else:  # Fall back for any other head token shape.
                        node = SExp(children=[SExp(value=token)])  # Create an anonymous list with one atom child.
            else:  # Reject empty head tokens.
                raise ParseError(f"Expected atom at position {pos}", pos)  # Raise with the failing offset.
        else:  # The head is a quoted string or a nested list.
            first = self._parse_expr()  # Parse the head expression.
            first_value = first.value  # Read the head expression value.
            if first.name is None and not first.children:  # Handle atom heads specially.
                if isinstance(first_value, (int, float)):  # Numeric atom heads become list names.
                    node = SExp(name=str(first_value))  # Create a named list node from the number.
                else:  # String atom heads become anonymous list children.
                    node = SExp(children=[first])  # Create an anonymous list carrying the atom.
            else:  # Nested list heads become anonymous list children.
                node = SExp(children=[first])  # Create an anonymous list carrying the head node.
        children = node.children  # Alias the accumulating child list.
        while True:  # Consume remaining children until the closing parenthesis.
            pos = self.pos  # Alias the current cursor.
            while pos < length and text[pos] in _WHITESPACE:  # Skip whitespace between children.
                pos += 1  # Advance past the whitespace character.
            while pos < length and text[pos] in _COMMENT_CHARS:  # Skip comment lines between children.
                while pos < length and text[pos] != "\n":  # Skip to the end of the comment line.
                    pos += 1  # Advance through the comment text.
                while pos < length and text[pos] in _WHITESPACE:  # Skip whitespace after the comment.
                    pos += 1  # Advance past the whitespace character.
            self.pos = pos  # Commit the cursor before inspecting the next token.
            if pos >= length:  # Reject unterminated lists.
                raise ParseError("Unexpected end of input, expected ')'", pos)  # Raise with the end-of-input offset.
            if text[pos] == ")":  # Detect the list terminator.
                self.pos = pos + 1  # Consume the closing parenthesis.
                break  # Stop consuming children.
            children.append(self._parse_expr())  # Parse and append the next child node.
        return node  # Return the completed list node.

    def _parse_string_node(self) -> SExp:  # Parse a quoted string atom node.
        node = SExp(value=self._parse_string())  # Build the atom from the decoded string value.
        node._originally_quoted = True  # Mark the atom as originally quoted.
        return node  # Return the quoted atom node.

    def _parse_string(self) -> str:  # Decode one quoted string literal.
        text = self.text  # Alias the source text for hot-path speed.
        length = self.length  # Alias the source length for hot-path speed.
        pos = self.pos + 1  # Skip the opening quote.
        start = pos  # Record the first content character.
        while pos < length:  # Fast path: scan for a plain end quote.
            char = text[pos]  # Inspect the current character.
            if char == '"':  # Found the closing quote.
                self.pos = pos + 1  # Consume the closing quote.
                return text[start:pos]  # Return the plain substring.
            elif char == "\\":  # Escapes require the slow path.
                break  # Exit the fast path.
            pos += 1  # Advance through plain string characters.
        result = [text[start:pos]] if pos > start else []  # Seed the slow-path buffer with the plain prefix.
        while pos < length:  # Slow path: decode escape sequences.
            char = text[pos]  # Inspect the current character.
            if char == '"':  # Found the closing quote.
                self.pos = pos + 1  # Consume the closing quote.
                return "".join(result)  # Return the assembled decoded string.
            elif char == "\\":  # Decode an escape sequence.
                pos += 1  # Move to the escaped character.
                if pos >= length:  # Reject dangling escapes.
                    raise ParseError("Unexpected end of input in escape sequence", pos)  # Raise with the failing offset.
                escaped = text[pos]  # Read the escaped character.
                result.append(_ESCAPE_MAP.get(escaped, escaped))  # Append the decoded escape result.
            else:  # Plain characters are copied through.
                result.append(char)  # Append the plain character.
            pos += 1  # Advance through the string content.
        raise ParseError("Unterminated string", pos)  # Raise when the string never closes.

    def _parse_atom(self) -> SExp:  # Parse one unquoted atom token.
        text = self.text  # Alias the source text for hot-path speed.
        length = self.length  # Alias the source length for hot-path speed.
        start = self.pos  # Record the atom start offset.
        pos = start  # Alias the scan cursor.
        while pos < length and text[pos] not in _ATOM_TERMINATORS:  # Scan to the end of the token.
            pos += 1  # Advance through the token characters.
        self.pos = pos  # Commit the cursor after the token.
        if pos == start:  # Reject empty atom tokens.
            raise ParseError(f"Expected atom at position {pos}", pos)  # Raise with the failing offset.
        token = text[start:pos]  # Extract the token text.
        first_char = token[0]  # Inspect the token start.
        if first_char.isdigit() or (first_char == "-" and len(token) > 1):  # Attempt numeric interpretation.
            try:  # Try to decode the token as a number.
                if "." in token or "e" in token or "E" in token:  # Floating-point spellings.
                    node = SExp(value=float(token))  # Build a float atom.
                else:  # Integer spellings.
                    node = SExp(value=int(token))  # Build an int atom.
                node._original_str = token  # Preserve the numeric source spelling.
                return node  # Return the numeric atom.
            except ValueError:  # Fall through for non-numeric digit-leading tokens.
                pass  # Treat the token as a bare string atom below.
        return SExp(value=token, _originally_bare=True)  # Return the bare string atom.

    def _skip_whitespace(self) -> None:  # Skip whitespace and comment lines at the cursor.
        text = self.text  # Alias the source text for hot-path speed.
        length = self.length  # Alias the source length for hot-path speed.
        pos = self.pos  # Alias the read cursor.
        while pos < length:  # Loop until a real token or end of input.
            char = text[pos]  # Inspect the current character.
            if char in _WHITESPACE:  # Skip ordinary whitespace.
                pos += 1  # Advance past the whitespace character.
            elif char in _COMMENT_CHARS:  # Skip a comment line.
                while pos < length and text[pos] != "\n":  # Skip to the end of the line.
                    pos += 1  # Advance through the comment text.
            else:  # A real token begins here.
                break  # Stop skipping.
        self.pos = pos  # Commit the cursor.


def parse_string(text: str, track_positions: bool = False) -> SExp:  # Parse one full S-expression document string.
    """Parse an S-expression string.

    Args:
        text: The S-expression text to parse.
        track_positions: If True, attach one-based line and column positions
            to every parsed node.

    Returns:
        The parsed SExp tree.

    Raises:
        ParseError: If the text is not valid S-expression syntax.
    """
    return Parser(text, track_positions=track_positions).parse()  # Parse the text with the requested position tracking.
