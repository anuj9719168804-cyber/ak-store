"""Test setup: the sandbox has no motor/pyrogram, so tiny stand-ins are registered before the
bot's own modules are imported. Real deployments never see this folder's stubs."""
import sys
import types


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    mod.__dict__.update(attrs)
    sys.modules.setdefault(name, mod)
    return mod


class _FakeClient:
    def __init__(self, *a, **k):
        pass

    def __getitem__(self, name):
        return self


_motor = _stub("motor")
_stub("motor.motor_asyncio", AsyncIOMotorClient=_FakeClient)
_motor.motor_asyncio = sys.modules["motor.motor_asyncio"]

try:
    import aiohttp  # noqa: F401
except ImportError:  # no network in the sandbox; gateway HTTP calls are not exercised by unit tests
    class _Timeout:
        def __init__(self, *a, **k):
            pass
    _stub("aiohttp", ClientTimeout=_Timeout, ClientSession=object, ClientError=Exception)


# ---- pyrogram: only when the real package is missing (the sandbox). Enough to import plugins. ----
try:
    import pyrogram  # noqa: F401
except ImportError:
    class _Any:
        """Callable, attribute-rich, supports & | ~ : stands in for filters, enums, types."""
        def __init__(self, *a, **k): pass
        def __call__(self, *a, **k): return _Any()
        def __getattr__(self, n): return _Any() if not n.startswith("__") else (_ for _ in ()).throw(AttributeError(n))
        def __and__(self, o): return _Any()
        __rand__ = __or__ = __ror__ = __and__
        def __invert__(self): return _Any()

    class _Client:
        handlers = []
        def __init__(self, *a, **k): pass
        @classmethod
        def _deco(cls, kind):
            def outer(*fa, **fk):
                def inner(fn):
                    cls.handlers.append((kind, fn))
                    return fn
                return inner
            return outer

    _Client.on_message = _Client._deco("message")
    _Client.on_callback_query = _Client._deco("callback")
    _Client.on_inline_query = _Client._deco("inline")
    _Client.on_chosen_inline_result = _Client._deco("chosen")
    _Client.on_chat_join_request = _Client._deco("join")

    class _Mod(types.ModuleType):
        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            val = _Client if name == "Client" else (type(name, (Exception,), {}) if name[:1].isupper() and name.endswith(("Error", "Wait", "Invalid", "Blocked", "Deactivated", "Participant", "Required", "Forbidden")) else _Any())
            setattr(self, name, val)
            return val

    for _n in ("pyrogram", "pyrogram.types", "pyrogram.enums", "pyrogram.errors", "pyrogram.handlers",
               "pyrogram.errors.pyromod", "pyrogram.errors.exceptions", "pyrogram.errors.exceptions.bad_request_400",
               "pyrogram.utils", "pyrogram.filters"):
        sys.modules.setdefault(_n, _Mod(_n))
    sys.modules["pyrogram"].filters = sys.modules["pyrogram.filters"]
    sys.modules["pyrogram"].Client = _Client
    sys.modules["pyrogram"].utils = sys.modules["pyrogram.utils"]
    sys.modules["pyrogram"].types = sys.modules["pyrogram.types"]
    sys.modules["pyrogram"].enums = sys.modules["pyrogram.enums"]
    sys.modules["pyrogram"].errors = sys.modules["pyrogram.errors"]
    sys.modules["pyrogram"].handlers = sys.modules["pyrogram.handlers"]
    sys.modules["pyrogram"].ContinuePropagation = type("ContinuePropagation", (Exception,), {})
    sys.modules["pyrogram.errors.exceptions.bad_request_400"].UserNotParticipant = type("UserNotParticipant", (Exception,), {})
    sys.modules["pyrogram.errors"].FloodWait = type("FloodWait", (Exception,), {})


# ---- small third-party packages that are only imported, never really used, by the plugins ----
for _pkg in ("humanize", "psutil", "requests", "quart", "hypercorn", "hypercorn.asyncio", "hypercorn.config", "dns"):
    try:
        __import__(_pkg)
    except ImportError:
        sys.modules.setdefault(_pkg, _Mod(_pkg) if "_Mod" in globals() else types.ModuleType(_pkg))


# keyboards must be inspectable in tests (which URL did the bot put on which button?)
if getattr(sys.modules.get("pyrogram.types"), "__class__", None).__name__ == "_Mod":
    class InlineKeyboardButton:
        def __init__(self, text=None, callback_data=None, url=None, **kw):
            self.text, self.callback_data, self.url = text, callback_data, url
    class InlineKeyboardMarkup:
        def __init__(self, inline_keyboard=None):
            self.inline_keyboard = inline_keyboard or []
    sys.modules["pyrogram.types"].InlineKeyboardButton = InlineKeyboardButton
    sys.modules["pyrogram.types"].InlineKeyboardMarkup = InlineKeyboardMarkup
