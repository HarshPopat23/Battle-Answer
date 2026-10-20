"""Real SDK fixture: state persists across tool calls on one transport session."""
import os
from pathlib import Path
import sys

from mcp.server.fastmcp import FastMCP

server = FastMCP('arena-integration-fixture', host='127.0.0.1', port=int(sys.argv[1]) if len(sys.argv) > 1 else 0)
count = 0


@server.tool()
def increment(amount: int) -> int:
    global count
    count += amount
    return count


@server.tool()
def write_note(text: str) -> str:
    Path('note.txt').write_text(text, encoding='utf-8')
    return 'saved'


@server.tool()
def environment() -> dict:
    return {'explicit': os.environ.get('EXPLICIT_VALUE'), 'unrelated': os.environ.get('ARENA_UNRELATED_TEST_KEY'),
            'home': os.environ.get('HOME')}


@server.tool()
def broken() -> str:
    raise ValueError('fixture failure')


if __name__ == '__main__':
    server.run(transport='streamable-http' if len(sys.argv) > 1 else 'stdio')
