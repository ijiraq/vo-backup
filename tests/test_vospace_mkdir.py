from unittest.mock import MagicMock, call

from vo_backup.vospace import VOSpace


def test_mkdir_p_creates_missing_parents():
    vos = VOSpace.__new__(VOSpace)
    vos._client = MagicMock()
    vos._path_exists = MagicMock(side_effect=lambda uri: uri == "vos:user")

    def fix_uri(uri):
        return uri

    vos.fix_uri = fix_uri
    vos.mkdir = MagicMock()

    vos.mkdir_p("vos:user/backups/laptop/current")

    vos.mkdir.assert_has_calls(
        [
            call("vos:user/backups"),
            call("vos:user/backups/laptop"),
            call("vos:user/backups/laptop/current"),
        ]
    )


def test_mkdir_p_skips_when_exists():
    vos = VOSpace.__new__(VOSpace)
    vos._path_exists = MagicMock(return_value=True)
    vos.fix_uri = lambda uri: uri
    vos.mkdir = MagicMock()

    vos.mkdir_p("vos:user/backups/laptop")

    vos.mkdir.assert_not_called()


def test_move_treats_false_return_as_success():
    vos = VOSpace.__new__(VOSpace)
    vos._client = MagicMock()
    vos._client.move.return_value = False
    vos.fix_uri = lambda uri: uri
    vos.mkdir_p = MagicMock()

    vos.move("vos:user/src", "vos:user/dest")

    vos._client.move.assert_called_once_with("vos:user/src", "vos:user/dest")


def test_move_propagates_client_error():
    vos = VOSpace.__new__(VOSpace)
    vos._client = MagicMock()
    vos._client.move.side_effect = OSError(2, "No such file")
    vos.fix_uri = lambda uri: uri
    vos.mkdir_p = MagicMock()

    try:
        vos.move("vos:user/missing", "vos:user/dest")
        assert False, "expected OSError"
    except OSError as exc:
        assert exc.errno == 2
