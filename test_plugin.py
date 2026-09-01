"""自检脚本：`python test_plugin.py`（无需 pytest / AstrBot 运行环境）。

只盖两处有分支的逻辑：
1. `/zmhelp` 菜单 —— 内置菜单、`help_menu_text` 自定义、空白回落、占位符替换
2. 数据目录迁移 —— 1.0.5 改名后老用户的 `ZM-QQManager` 目录要整体改名过来
"""
import importlib.util
import json
import sys
import tempfile
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent


class _Stub:
    """任意属性/调用都返回自己，够 astrbot 那几个装饰器用。"""

    def __getattr__(self, name):
        return _Stub()

    def __call__(self, *args, **kwargs):
        return lambda func: func

    def __getitem__(self, key):
        return _Stub()


def _stub_astrbot():
    def mod(name, **attrs):
        m = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(m, key, value)
        sys.modules[name] = m
        return m

    class Star:
        def __init__(self, *args, **kwargs):
            pass

    mod("astrbot")
    mod("astrbot.api", AstrBotConfig=dict, logger=_Stub())
    mod("astrbot.api.event", AstrMessageEvent=object, filter=_Stub())
    mod("astrbot.api.star", Context=object, Star=Star,
        register=lambda *a, **kw: (lambda cls: cls))


def _load_plugin():
    """把插件目录当包加载，相对导入 (.core.xxx) 才成立。"""
    spec = importlib.util.spec_from_file_location(
        "zmplugin", HERE / "__init__.py", submodule_search_locations=[str(HERE)]
    )
    pkg = importlib.util.module_from_spec(spec)
    sys.modules["zmplugin"] = pkg
    spec.loader.exec_module(pkg)
    return importlib.import_module("zmplugin.main")


def test_help_menu(main):
    cls = main.ZMQQGroupmgr
    inst = object.__new__(cls)
    inst.files = types.SimpleNamespace(cooldown_seconds=lambda: 300)

    inst.config = {}
    builtin = cls._help_text(inst)
    assert builtin.startswith(f"{main.PLUGIN_NAME} v{main.PLUGIN_VERSION} 命令一览"), builtin[:60]
    assert "【禁言】" in builtin and "时长单位" in builtin
    assert "下载冷却: 5分钟" in builtin, "cooldown_text 没接上"
    assert "QQManager" not in builtin, "还有旧名字残留"

    inst.config = {"help_menu_text": "  {name} v{version} / 冷却 {cooldown}  "}
    assert cls._help_text(inst) == f"{main.PLUGIN_NAME} v{main.PLUGIN_VERSION} / 冷却 5分钟"

    inst.config = {"help_menu_text": "   \n  "}
    assert cls._help_text(inst) == builtin, "全空白应回落内置菜单"

    print("  help 菜单: 内置 / 自定义 / 空白回落 OK")


def test_data_dir_migration():
    spec = importlib.util.spec_from_file_location("zmstore", HERE / "core" / "store.py")
    store = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(store)

    def run(setup):
        root = Path(tempfile.mkdtemp())
        path_mod = types.ModuleType("astrbot.core.utils.astrbot_path")
        path_mod.get_astrbot_data_path = lambda: str(root)
        sys.modules["astrbot.core"] = types.ModuleType("astrbot.core")
        sys.modules["astrbot.core.utils"] = types.ModuleType("astrbot.core.utils")
        sys.modules["astrbot.core.utils.astrbot_path"] = path_mod
        setup(root / "plugin_data")
        return root, store.get_data_dir()

    def with_legacy(plugin_data):
        old = plugin_data / "ZM-QQManager"
        old.mkdir(parents=True)
        (old / "settings.json").write_text(json.dumps({"k": "v"}), encoding="utf-8")

    root, got = run(with_legacy)
    assert got.name == "ZM-QQGroupmgr", got
    assert json.loads((got / "settings.json").read_text(encoding="utf-8")) == {"k": "v"}
    assert not (root / "plugin_data" / "ZM-QQManager").exists(), "旧目录应已改名"
    assert store.get_data_dir() == got, "重复调用应幂等"

    _, got = run(lambda plugin_data: plugin_data.mkdir(parents=True))
    assert got.name == "ZM-QQGroupmgr" and got.is_dir(), "全新安装应直接建新目录"

    def both(plugin_data):
        (plugin_data / "ZM-QQManager").mkdir(parents=True)
        (plugin_data / "ZM-QQManager" / "a.json").write_text("1", encoding="utf-8")
        (plugin_data / "ZM-QQGroupmgr").mkdir(parents=True)

    root, got = run(both)
    assert got.name == "ZM-QQGroupmgr"
    assert (root / "plugin_data" / "ZM-QQManager" / "a.json").exists(), \
        "新目录已存在时不该动旧目录"

    print("  数据目录: 老用户迁移 / 新装 / 双目录并存 / 幂等 OK")


def test_entry_path(main):
    """数据目录改名后，files.json 里存的旧绝对路径要能按文件名回落。"""
    repo_cls = sys.modules["zmplugin.core.files"].FileRepository
    repo = object.__new__(repo_cls)
    repo.dir = Path(tempfile.mkdtemp()) / "files"
    repo.dir.mkdir(parents=True)
    (repo.dir / "guoclient.zip").write_bytes(b"x")

    stale = {"path": str(Path("/nowhere/plugin_data/ZM-QQManager/files/guoclient.zip"))}
    assert repo._entry_path(stale) == repo.dir / "guoclient.zip", "旧路径应回落到当前仓库"

    live = {"path": str(repo.dir / "guoclient.zip")}
    assert repo._entry_path(live) == repo.dir / "guoclient.zip", "有效路径应原样返回"

    missing = {"path": str(Path("/nowhere/files/never-uploaded.zip"))}
    assert not repo._entry_path(missing).exists(), "确实丢了的文件仍应判定为不存在"

    escape = {"path": "/nowhere/files/../../../etc/passwd"}
    got = repo._entry_path(escape)
    assert not str(got).startswith(str(repo.dir)) or got.name == "passwd" and not got.exists()

    assert repo._entry_path({}) == repo.dir, "空 path 不应崩"
    print("  文件仓库: 旧路径回落 / 有效路径 / 真丢失 / 越界拦截 OK")


if __name__ == "__main__":
    _stub_astrbot()
    main = _load_plugin()
    test_help_menu(main)
    test_entry_path(main)
    test_data_dir_migration()
    print(f"全部自检通过 —— {main.PLUGIN_NAME} v{main.PLUGIN_VERSION}")
