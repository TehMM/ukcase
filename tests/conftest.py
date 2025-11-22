from datetime import datetime, timezone
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Provide a lightweight SQLAlchemy stub when the dependency is unavailable.
if "sqlalchemy" not in sys.modules:  # pragma: no cover
    store: dict[type, dict[int, object]] = {}

    class FakeType:
        def __init__(self, *args, **kwargs):
            pass

    class FakeColumn:
        def __init__(self, *args, default=None, server_default=None, primary_key=False, **kwargs):
            self.default = default
            self.server_default = server_default
            self.primary_key = primary_key
            self.name = ""

        def __set_name__(self, owner, name):
            self.name = name

        def _default_value(self):
            if self.default is not None:
                return self.default() if callable(self.default) else self.default
            if self.server_default is not None:
                raw = str(self.server_default).strip("'")
                try:
                    return float(raw)
                except ValueError:
                    return raw
            return None

        def __get__(self, instance, owner):
            if instance is None:
                return self
            return instance.__dict__.get(self.name, self._default_value())

        def __set__(self, instance, value):
            instance.__dict__[self.name] = value

        def __eq__(self, other):
            return lambda obj: getattr(obj, self.name, None) == other

        def desc(self):
            return self

    class FakeMetadata:
        def drop_all(self, bind=None):
            for bucket in store.values():
                bucket.clear()

        def create_all(self, bind=None):
            # Nothing to do for in-memory store.
            return None

    class Base:
        metadata = FakeMetadata()

        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

    def declarative_base():
        return Base

    class FakeQuery:
        def __init__(self, results):
            self._results = results

        def all(self):
            return list(self._results)

        def order_by(self, *args, **kwargs):
            return self

        def first(self):
            return self._results[0] if self._results else None

        def count(self):
            return len(self._results)

        def __iter__(self):
            return iter(self._results)

    class FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def scalars(self):
            return self

        def scalar_one_or_none(self):
            return self._rows[0] if self._rows else None

        def __iter__(self):
            return iter(self._rows)

    class FakeSelect:
        def __init__(self, model):
            self.model = model
            self.predicates = []

        def where(self, predicate):
            self.predicates.append(predicate)
            return self

        def order_by(self, *args, **kwargs):
            return self

        def execute(self, session):
            rows = list(session._store.get(self.model, {}).values())
            for predicate in self.predicates:
                rows = [row for row in rows if predicate(row)]
            return FakeResult(rows)

    def select(model):
        return FakeSelect(model)

    class FakeSession:
        def __init__(self):
            self._store = store

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def add(self, obj):
            bucket = self._store.setdefault(obj.__class__, {})
            if getattr(obj, "id", None) is None:
                obj.id = len(bucket) + 1
            bucket[obj.id] = obj

        def flush(self):
            return None

        def commit(self):
            return None

        def close(self):
            return None

        def get(self, model, obj_id):
            return self._store.get(model, {}).get(obj_id)

        def execute(self, statement):
            if hasattr(statement, "execute"):
                return statement.execute(self)
            return FakeResult([])

        def query(self, model):
            return FakeQuery(list(self._store.get(model, {}).values()))

        def delete(self, obj):
            bucket = self._store.get(obj.__class__, {})
            bucket.pop(getattr(obj, "id", None), None)

    def sessionmaker(**kwargs):
        def factory():
            return FakeSession()

        return factory

    def create_engine(url, **kwargs):
        return types.SimpleNamespace(url=url)

    class Func:
        @staticmethod
        def now():
            return datetime.now(timezone.utc)

    def text(value):
        return value

    def relationship(*args, **kwargs):
        return None

    sa = types.ModuleType("sqlalchemy")
    sa.create_engine = create_engine
    sa.BigInteger = sa.Boolean = sa.Date = sa.DateTime = sa.Integer = sa.Numeric = sa.Text = FakeType
    sa.ForeignKey = lambda target, **kwargs: target
    sa.Index = lambda *args, **kwargs: None
    sa.func = Func()
    sa.text = text
    sa.select = select

    orm = types.ModuleType("sqlalchemy.orm")
    orm.Mapped = object
    orm.declarative_base = declarative_base
    orm.sessionmaker = sessionmaker
    orm.mapped_column = FakeColumn
    orm.relationship = relationship
    orm.Session = FakeSession

    dialects = types.ModuleType("sqlalchemy.dialects")
    postgres = types.ModuleType("sqlalchemy.dialects.postgresql")
    postgres.ARRAY = lambda *args, **kwargs: FakeType()
    dialects.postgresql = postgres

    sys.modules["sqlalchemy"] = sa
    sys.modules["sqlalchemy.orm"] = orm
    sys.modules["sqlalchemy.dialects"] = dialects
    sys.modules["sqlalchemy.dialects.postgresql"] = postgres


# Provide a minimal pydantic_settings stub when absent.
if "pydantic_settings" not in sys.modules:  # pragma: no cover
    pydantic_settings = types.ModuleType("pydantic_settings")

    class BaseSettings:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

    class SettingsConfigDict(dict):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)

    pydantic_settings.BaseSettings = BaseSettings
    pydantic_settings.SettingsConfigDict = SettingsConfigDict
    sys.modules["pydantic_settings"] = pydantic_settings


# Provide a small Typer stub when typer is unavailable.
if "typer" not in sys.modules:  # pragma: no cover
    typer = types.ModuleType("typer")
    typer_output: list[str] = []

    class Typer:
        def __init__(self, *args, **kwargs):
            self.commands = {}
            self.subapps = {}

        def command(self, *args, **kwargs):
            name = args[0] if args else None

            def decorator(func):
                cmd_name = name or func.__name__.replace("_", "-")
                self.commands[cmd_name] = func
                return func

            return decorator

        def add_typer(self, app, name=None):
            if name is not None:
                self.subapps[name] = app

        def __call__(self, *args, **kwargs):
            return None

    def echo(message, err=False):
        typer_output.append(f"{message}\n")

    def Argument(*args, default=None, **kwargs):
        return default if default is not None else (args[0] if args else None)

    def Option(*args, default=None, **kwargs):
        return default if default is not None else (args[0] if args else None)

    def Exit(code=0):  # pragma: no cover
        raise SystemExit(code)

    typer.Typer = Typer
    typer.echo = echo
    typer.Exit = Exit
    typer.Argument = Argument
    typer.Option = Option
    sys.modules["typer"] = typer

    testing = types.ModuleType("typer.testing")

    class Result:
        def __init__(self, exit_code=0, stdout=""):
            self.exit_code = exit_code
            self.stdout = stdout

    class CliRunner:
        def _call_command(self, app_obj, args):
            import inspect

            if not args:
                raise SystemExit(0)

            command_name = args[0]
            if command_name in app_obj.subapps:
                return self._call_command(app_obj.subapps[command_name], args[1:])

            func = app_obj.commands.get(command_name)
            if func is None:
                raise SystemExit(1)

            sig = inspect.signature(func)
            positional_args = []
            options: dict[str, object] = {}
            remaining = list(args[1:])
            while remaining:
                token = remaining.pop(0)
                if token.startswith("--"):
                    key = token.lstrip("-")
                    if not remaining:
                        options[key] = True
                        continue
                    value = remaining.pop(0)
                    options[key] = value
                else:
                    positional_args.append(token)

            bound_args = []
            kwargs = {}
            for param in sig.parameters.values():
                if param.kind == inspect.Parameter.POSITIONAL_OR_KEYWORD:
                    if positional_args:
                        raw = positional_args.pop(0)
                        bound_args.append(self._convert(raw, param.annotation))
                    elif param.name in options:
                        bound_args.append(self._convert(options.pop(param.name), param.annotation))
                if param.name in options:
                    kwargs[param.name] = self._convert(options[param.name], param.annotation)

            return func(*bound_args, **kwargs)

        @staticmethod
        def _convert(value, annotation):
            if annotation in (int, float):
                try:
                    return annotation(value)
                except Exception:
                    return value
            return value

        def invoke(self, app, args):
            typer_output.clear()
            exit_code = 0
            try:
                self._call_command(app, args)
            except SystemExit as exc:  # pragma: no cover - mirrors typer behaviour
                exit_code = exc.code
            stdout = "".join(typer_output)
            return Result(exit_code=exit_code, stdout=stdout)

    testing.CliRunner = CliRunner
    sys.modules["typer.testing"] = testing


# Provide lightweight feedparser/httpx stubs when missing.
if "feedparser" not in sys.modules:  # pragma: no cover
    feedparser = types.ModuleType("feedparser")

    def _parse(text):
        import xml.etree.ElementTree as ET
        import textwrap

        ns = {"atom": "http://www.w3.org/2005/Atom"}
        normalized = textwrap.dedent(text).strip()
        root = ET.fromstring(normalized)
        entries = []
        for elem in root.findall("atom:entry", ns):
            entry = {}
            id_elem = elem.find("atom:id", ns)
            link_elem = elem.find("atom:link", ns)
            title_elem = elem.find("atom:title", ns)
            updated_elem = elem.find("atom:updated", ns)
            published_elem = elem.find("atom:published", ns)
            if id_elem is not None and id_elem.text:
                entry["id"] = id_elem.text
            if link_elem is not None:
                entry["link"] = link_elem.attrib.get("href")
            if title_elem is not None and title_elem.text:
                entry["title"] = title_elem.text
            if updated_elem is not None and updated_elem.text:
                entry["updated_parsed"] = datetime.strptime(updated_elem.text, "%Y-%m-%dT%H:%M:%SZ").timetuple()
            if published_elem is not None and published_elem.text:
                entry["published_parsed"] = datetime.strptime(published_elem.text, "%Y-%m-%dT%H:%M:%SZ").timetuple()
            entries.append(entry)
        return types.SimpleNamespace(entries=entries)

    feedparser.parse = _parse
    sys.modules["feedparser"] = feedparser


if "httpx" not in sys.modules:  # pragma: no cover
    httpx = types.ModuleType("httpx")

    class Response:
        def __init__(self, status_code: int, text: str = "", content: bytes | None = None, request=None):
            self.status_code = status_code
            self.text = text
            self.content = content if content is not None else text.encode()
            self.request = request

        def raise_for_status(self):
            if self.status_code >= 400:
                raise HTTPStatusError(f"status {self.status_code}", request=self.request, response=self)

    class HTTPStatusError(Exception):
        def __init__(self, message: str, request=None, response=None):
            super().__init__(message)
            self.request = request
            self.response = response

    class Codes:
        OK = 200
        TOO_MANY_REQUESTS = 429

    httpx.Response = Response
    httpx.HTTPStatusError = HTTPStatusError
    httpx.codes = Codes()

    def _missing_get(*args, **kwargs):  # pragma: no cover
        return Response(status_code=200, text="")

    httpx.get = _missing_get
    sys.modules["httpx"] = httpx
