"""Static regression tests for the skill-doc path-transport contract.

The skill docs (graphify/skill.md and its mirror skills/graphify/skill.md)
are consumed by an agent at runtime, so nothing else in the suite can see
them. These tests are inert by design: they read the two documents as text
and check the contract that the scan path always travels through
.graphify_input_path, guarded, and is never interpolated into code or shell.
No project modules are imported, no subprocess, no network.

Mutation checks (remove the fix, a test must fail):
- Reintroduce any 'INPUT_PATH' placeholder -> test_no_input_path_placeholder.
- Drop the guard after a SCAN_ROOT read -> test_every_read_is_guarded.
- Drop encoding='utf-8' from a read -> test_every_read_pins_utf8.
- Route watch through shell substitution again -> test_no_shell_path_substitution.
- Break a python3 -c block -> test_embedded_python_blocks_parse.
"""

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DOCS = (
    REPO_ROOT / 'graphify' / 'skill.md',
    REPO_ROOT / 'skills' / 'graphify' / 'skill.md',
)

READ_RE = re.compile(r"^SCAN_ROOT = Path\('\.graphify_input_path'\)\.read_text\(([^)]*)\)", re.M)
# multiline: closing quote starts a line, optionally followed by a redirection
PY_BLOCK_RE = re.compile(r'python3 -c "\n(.*?)\n"[^\n]*\n', re.S)
PY_ONELINE_RE = re.compile(r'python3 -c "([^"\n]+)"')


def _read(doc):
    assert doc.is_file(), f'missing skill doc: {doc}'
    return doc.read_text(encoding='utf-8')


def _python_blocks(text):
    """Extract embedded python3 -c sources, undoing bash double-quote escaping."""
    blocks = [m.replace('\\"', '"') for m in PY_BLOCK_RE.findall(text)]
    blocks += list(PY_ONELINE_RE.findall(text))
    return blocks


def test_no_input_path_placeholder():
    for doc in SKILL_DOCS:
        assert 'INPUT_PATH' not in _read(doc), f'{doc}: leftover INPUT_PATH placeholder'


def test_every_read_pins_utf8():
    for doc in SKILL_DOCS:
        reads = READ_RE.findall(_read(doc))
        assert reads, f'{doc}: no .graphify_input_path read found (transport changed?)'
        for args in reads:
            assert "encoding='utf-8'" in args, f'{doc}: read without encoding=\'utf-8\': read_text({args})'


def test_every_read_is_guarded():
    for doc in SKILL_DOCS:
        lines = _read(doc).splitlines()
        reads = [i for i, ln in enumerate(lines) if READ_RE.match(ln)]
        assert reads, f'{doc}: no .graphify_input_path read found (transport changed?)'
        for i in reads:
            following = '\n'.join(lines[i + 1:i + 3])
            assert 'if not SCAN_ROOT' in following and 'SystemExit' in following, (
                f'{doc}: unguarded read at line {i + 1} - empty file resolves to cwd'
            )


def test_no_shell_path_substitution():
    for doc in SKILL_DOCS:
        text = _read(doc)
        assert '$(cat .graphify_input_path)' not in text, (
            f'{doc}: path file consumed by shell substitution - empty/missing file passes an empty argv'
        )
        assert not re.search(r'python3 -m graphify\.watch[^\n]*\$\(', text), (
            f'{doc}: watch command substitutes the path file in shell'
        )


def test_watch_uses_guarded_transport():
    for doc in SKILL_DOCS:
        blocks = [b for b in _python_blocks(_read(doc)) if 'graphify.watch' in b]
        assert blocks, f'{doc}: no python watch block found'
        for block in blocks:
            assert 'if not SCAN_ROOT' in block and 'SystemExit' in block, (
                f'{doc}: watch block missing the empty/invalid guard'
            )
            assert 'SCAN_ROOT' in block and '$(cat' not in block, (
                f'{doc}: watch block must pass SCAN_ROOT as one argv element'
            )


def test_gitignore_guidance_present():
    for doc in SKILL_DOCS:
        text = _read(doc)
        assert '.gitignore' in text and '.graphify_*' in text, (
            f'{doc}: no guidance to gitignore the .graphify_* scratch files'
        )


def test_cleanup_covers_input_path():
    for doc in SKILL_DOCS:
        assert re.search(r'rm -f [^\n]*\.graphify_input_path', _read(doc)), (
            f'{doc}: pipeline cleanup does not remove .graphify_input_path'
        )


def test_embedded_python_blocks_parse():
    for doc in SKILL_DOCS:
        blocks = _python_blocks(_read(doc))
        assert blocks, f'{doc}: no python3 -c blocks found (doc structure changed?)'
        for n, block in enumerate(blocks, 1):
            try:
                ast.parse(block)
            except SyntaxError as e:
                raise AssertionError(f'{doc}: python3 -c block #{n} does not parse: {e}')


def test_mirror_parity_on_transport_blocks():
    """The two skill docs may drift in prose (pre-existing), but every code
    block that touches .graphify_input_path must be identical in both."""
    per_doc = []
    for doc in SKILL_DOCS:
        blocks = [b for b in _python_blocks(_read(doc)) if '.graphify_input_path' in b]
        assert blocks, f'{doc}: no path-transport code blocks found'
        per_doc.append(blocks)
    assert per_doc[0] == per_doc[1], (
        'mirrored skill docs disagree on .graphify_input_path code blocks'
    )
