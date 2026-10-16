import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

_SCRIPT = Path(__file__).resolve().parents[1] / "get_size_recursive.py"
_spec = importlib.util.spec_from_file_location("get_size_recursive", _SCRIPT)
gsr = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules["get_size_recursive"] = gsr
_spec.loader.exec_module(gsr)


def _container(uri: str, children: list) -> SimpleNamespace:
    return SimpleNamespace(
        uri=uri,
        target=None,
        node_list=children,
        islink=lambda: False,
        isdir=lambda: True,
        get_info=lambda: {"size": 0},
    )


def _file(uri: str, size: int) -> SimpleNamespace:
    return SimpleNamespace(
        uri=uri,
        target=None,
        node_list=[],
        islink=lambda: False,
        isdir=lambda: False,
        get_info=lambda: {"size": size},
    )


def _link(uri: str, target: str, size: int = 999) -> SimpleNamespace:
    return SimpleNamespace(
        uri=uri,
        target=target,
        node_list=[],
        islink=lambda: True,
        isdir=lambda: False,
        get_info=lambda: {"size": size},
    )


def _fetch_from(nodes: dict[str, SimpleNamespace]):
    def fetch_node(uri: str):
        return nodes[uri]

    return fetch_node


def test_nested_data_files_sum_size_and_count():
    nested = _file("vos:u/root/sub/nested.dat", 99)
    sub = _container("vos:u/root/sub", [nested])
    data = _file("vos:u/root/file.bin", 42)
    root = _container("vos:u/root", [data, sub])
    nodes = {
        "vos:u/root": root,
        "vos:u/root/sub": sub,
    }

    result = gsr.walk_size("vos:u/root", fetch_node=_fetch_from(nodes), workers=2)

    assert result.size == 141
    assert result.files == 2
    assert result.skipped_links == 0


def test_child_links_are_not_followed_or_counted():
    target_file = _file("vos:u/elsewhere/linked.txt", 1000)
    link = _link("vos:u/root/linked.txt", "vos:u/elsewhere/linked.txt", size=7)
    data = _file("vos:u/root/file.bin", 42)
    root = _container("vos:u/root", [data, link])
    fetch_node = MagicMock(
        side_effect=_fetch_from(
            {
                "vos:u/root": root,
                "vos:u/elsewhere/linked.txt": target_file,
            }
        )
    )

    result = gsr.walk_size("vos:u/root", fetch_node=fetch_node, workers=2)

    assert result.size == 42
    assert result.files == 1
    assert result.skipped_links == 1
    fetch_node.assert_called_once_with("vos:u/root")


def test_start_uri_link_is_resolved_once():
    nested = _file("vos:u/real/file.bin", 50)
    real = _container("vos:u/real", [nested])
    pointer = _link("vos:u/latest", "vos:u/real")
    fetch_node = MagicMock(
        side_effect=_fetch_from(
            {
                "vos:u/latest": pointer,
                "vos:u/real": real,
            }
        )
    )

    result = gsr.walk_size("vos:u/latest", fetch_node=fetch_node, workers=2)

    assert result.size == 50
    assert result.files == 1
    assert result.skipped_links == 0
    assert fetch_node.call_count == 2
    fetch_node.assert_any_call("vos:u/latest")
    fetch_node.assert_any_call("vos:u/real")
