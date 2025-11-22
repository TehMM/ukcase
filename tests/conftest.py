from datetime import datetime, timezone
from pathlib import Path
import os
import sys
import textwrap
import time
import types
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Provide a lightweight SQLAlchemy stub so tests remain self-contained even
# when SQLAlchemy is not installed in the environment.
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

        def limit(self, _limit):
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

        def all(self):
            return list(self._rows)

    class FakeSelect:
        def __init__(self, model):
            self.model = model
            self.predicates = []

        def where(self, predicate):
            self.predicates.append(predicate)
            return self

        def order_by(self, *args, **kwargs):
            return self

        def limit(self, _limit):
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


# Provide a lightweight feedparser stub for tests (always overrides the real
# library if it has not been imported yet). This avoids a hard dependency on
# feedparser and keeps tests hermetic.
if "feedparser" not in sys.modules:  # pragma: no cover
    feedparser = types.ModuleType("feedparser")

    def _parse_feed(text: str = "", **_: object):
        entries: list[dict[str, object]] = []
        if not isinstance(text, str):
            return types.SimpleNamespace(entries=entries, bozo=False)

        content = textwrap.dedent(text).strip()
        if not content:
            return types.SimpleNamespace(entries=entries, bozo=False)

        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            return types.SimpleNamespace(entries=entries, bozo=False)

        ns = {"atom": "http://www.w3.org/2005/Atom"}

        def _parse_time(element: ET.Element | None) -> time.struct_time | None:
            if element is None or not element.text:
                return None
            try:
                dt = datetime.fromisoformat(element.text.replace("Z", ""))
            except Exception:
                return None
            return dt.timetuple()

        for entry_el in root.findall("atom:entry", ns):
            entry: dict[str, object] = {}

            id_el = entry_el.find("atom:id", ns)
            if id_el is not None:
                entry["id"] = id_el.text

            link_el = entry_el.find("atom:link", ns)
            if link_el is not None:
                entry["link"] = link_el.attrib.get("href")

            title_el = entry_el.find("atom:title", ns)
            if title_el is not None:
                entry["title"] = title_el.text

            updated = _parse_time(entry_el.find("atom:updated", ns))
            if updated:
                entry["updated_parsed"] = updated

            published = _parse_time(entry_el.find("atom:published", ns))
            if published:
                entry["published_parsed"] = published

            entries.append(entry)

        return types.SimpleNamespace(entries=entries, bozo=False)

    feedparser.parse = _parse_feed
    sys.modules["feedparser"] = feedparser


# Provide a minimal httpx stub so imports succeed without the dependency.
if "httpx" not in sys.modules:  # pragma: no cover
    httpx = types.ModuleType("httpx")

    class _Codes:
        OK = 200
        TOO_MANY_REQUESTS = 429

    class _Request:
        def __init__(self, url: str):
            self.url = url

    class Response:
        def __init__(self, text: str = "", status_code: int = 200, url: str = "", content=None):
            self.text = text
            self.content = content if content is not None else text.encode()
            self.status_code = status_code
            self.request = _Request(url)

        def raise_for_status(self):
            if self.status_code >= 400:
                raise HTTPStatusError(
                    f"Unexpected status code {self.status_code}",
                    request=self.request,
                    response=self,
                )

    class HTTPStatusError(Exception):
        def __init__(self, message: str, request=None, response=None):
            super().__init__(message)
            self.request = request
            self.response = response

    def get(url: str, timeout=None, headers=None):
        return Response(text="", status_code=_Codes.OK, url=url)

    httpx.codes = _Codes()
    httpx.HTTPStatusError = HTTPStatusError
    httpx.Response = Response
    httpx.get = get

    sys.modules["httpx"] = httpx


# Provide a minimal pydantic_settings stub so tests do not require the real
# dependency.
if "pydantic_settings" not in sys.modules:  # pragma: no cover
    pydantic_settings = types.ModuleType("pydantic_settings")

    class BaseSettings:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

            for env_key, attr in {
                "UKCASE_ADMIN_USERNAME": "admin_username",
                "UKCASE_ADMIN_PASSWORD": "admin_password",
                "UKCASE_CHANGEDTECTION_WEBHOOK_SECRET": "changedetection_webhook_secret",
                "UKCASE_DATABASE_URL": "database_url",
                "UKCASE_REDIS_URL": "redis_url",
                "UKCASE_HTTP_USER_AGENT": "http_user_agent",
                "UKCASE_XML_STORAGE_ROOT": "xml_storage_root",
            }.items():
                if env_key in os.environ and not getattr(self, attr, None):
                    setattr(self, attr, os.environ[env_key])

    class SettingsConfigDict(dict):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)

    pydantic_settings.BaseSettings = BaseSettings
    pydantic_settings.SettingsConfigDict = SettingsConfigDict
    sys.modules["pydantic_settings"] = pydantic_settings


# Provide a lightweight FastAPI stub only when the dependency is missing.
try:  # pragma: no cover
    import fastapi  # noqa: F401
except ImportError:  # pragma: no cover
    import base64
    import inspect
    import json

    fastapi = types.ModuleType("fastapi")

    class HTTPException(Exception):
        def __init__(self, status_code: int, detail: str | None = None, headers: dict | None = None):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail
            self.headers = headers or {}

    class Depends:
        def __init__(self, dependency):
            self.dependency = dependency

    class Query:
        def __init__(self, default=...):
            self.default = default

    class Request:
        def __init__(self, headers=None, auth=None, query_params=None):
            self.headers = headers or {}
            self.auth = auth
            self.query_params = query_params or {}

    class Response:
        def __init__(self, content="", status_code: int = 200, headers=None):
            self.content = content
            self.text = content if isinstance(content, str) else str(content)
            self.status_code = status_code
            self.headers = headers or {}

        def json(self):
            return json.loads(self.text)

    class HTMLResponse(Response):
        pass

    class JSONResponse(Response):
        def __init__(self, content=None, status_code: int = 200, headers=None):
            import json as _json

            super().__init__(
                content=_json.dumps(content or {}),
                status_code=status_code,
                headers=headers,
            )

    class RedirectResponse(Response):
        def __init__(self, url: str, status_code: int = 302, headers=None):
            headers = headers or {}
            headers.setdefault("location", url)
            super().__init__(content="", status_code=status_code, headers=headers)

    def _render_template(context):
        parts: list[str] = []
        if "segments" in context:
            names = [getattr(seg, "name", str(seg)) for seg in context["segments"]]
            parts.append(";".join(names))
        if "result" in context:
            res = context["result"]
            run_status = getattr(getattr(res, "run", None), "status", "")
            parts.append(
                f"{run_status} new={res.new_judgments} skipped={res.skipped_existing} failed={res.failed_items}"
            )
        if "runs" in context:
            parts.append(
                ",".join(str(getattr(run, "id", run)) for run in context.get("runs", []))
            )
        if "run" in context:
            run = context["run"]
            parts.append(str(getattr(run, "status", "")))
            parts.append(str(getattr(run, "id", "")))
        if "items" in context:
            parts.append(
                ",".join(getattr(item, "canonical_uri", str(item)) for item in context.get("items", []))
            )
        return " | ".join([part for part in parts if part]) or ""

    class TemplateResponse(HTMLResponse):
        def __init__(self, template_name: str, context: dict, status_code: int = 200):
            super().__init__(content=_render_template(context), status_code=status_code)

    class Jinja2Templates:
        def __init__(self, directory: str):
            self.directory = directory

        def TemplateResponse(self, template_name: str, context: dict, status_code: int = 200):
            return TemplateResponse(template_name, context, status_code=status_code)

    class _Status:
        HTTP_401_UNAUTHORIZED = 401
        HTTP_403_FORBIDDEN = 403
        HTTP_404_NOT_FOUND = 404
        HTTP_422_UNPROCESSABLE_ENTITY = 422
        HTTP_302_FOUND = 302

    status = _Status()

    class _Route:
        def __init__(self, path, method, func):
            self.path = path
            self.method = method
            self.func = func

    class APIRouter:
        def __init__(self):
            self.routes = []

        def get(self, path, response_class=HTMLResponse):
            def decorator(func):
                self.routes.append(_Route(path, "GET", func))
                return func

            return decorator

        def post(self, path, response_class=HTMLResponse):
            def decorator(func):
                self.routes.append(_Route(path, "POST", func))
                return func

            return decorator

    def _match_route(path: str, pattern: str):
        path_parts = path.strip("/").split("/")
        pattern_parts = pattern.strip("/").split("/")
        if len(path_parts) != len(pattern_parts):
            return None
        params = {}
        for path_part, pattern_part in zip(path_parts, pattern_parts):
            if pattern_part.startswith("{") and pattern_part.endswith("}"):
                name = pattern_part.strip("{}")
                params[name] = path_part
            elif path_part != pattern_part:
                return None
        return params

    def _resolve_dependencies(func, request, path_params, query_params):
        signature = inspect.signature(func)
        kwargs = {}
        for name, param in signature.parameters.items():
            default = param.default
            if isinstance(default, Query):
                value = query_params.get(name, default.default if default.default is not inspect._empty else None)
                if param.annotation is int:
                    try:
                        value = int(value)
                    except Exception:
                        pass
                kwargs[name] = value
                continue
            if isinstance(default, Depends):
                dep = default.dependency
                if isinstance(dep, HTTPBasic):
                    kwargs[name] = dep(request)
                    continue
                if callable(dep):
                    dep_kwargs = _resolve_dependencies(dep, request, path_params, query_params)
                    value = dep(**dep_kwargs)
                else:
                    value = dep
                if hasattr(value, "__iter__") and not isinstance(value, (str, bytes, dict)):
                    try:
                        value = next(value)
                    except StopIteration:
                        value = None
                kwargs[name] = value
                continue
            if name in path_params:
                value = path_params[name]
                if param.annotation is int:
                    try:
                        value = int(value)
                    except Exception:
                        pass
                kwargs[name] = value
                continue
            kwargs[name] = default if default is not inspect._empty else None
        return kwargs

    class TestResponse:
        def __init__(self, response: Response):
            self.status_code = response.status_code
            self.headers = {k.lower(): v for k, v in response.headers.items()}
            self.text = response.text
            self.content = response.content

        def json(self):
            import json as _json

            return _json.loads(self.text)

    class TestClient:
        def __init__(self, app):
            self.app = app

        def _find_route(self, method: str, path: str):
            for route in self.app.routes:
                params = _match_route(path, route.path)
                if route.method == method and params is not None:
                    return route, params
            for router in getattr(self.app, "routers", []):
                for route in router.routes:
                    params = _match_route(path, route.path)
                    if route.method == method and params is not None:
                        return route, params
            return None, None

        def _handle(self, method: str, path: str, params=None, auth=None, data=None):
            params = params or {}
            route, path_params = self._find_route(method, path)
            if route is None:
                return TestResponse(Response(status_code=404, content="Not found"))
            request = Request(headers={}, auth=auth, query_params=params)
            try:
                kwargs = _resolve_dependencies(route.func, request, path_params or {}, params)
                result = route.func(**kwargs)
                if inspect.iscoroutine(result):
                    import asyncio

                    result = asyncio.run(result)
            except HTTPException as exc:
                return TestResponse(Response(content=str(exc.detail), status_code=exc.status_code, headers=exc.headers))
            if isinstance(result, Response):
                return TestResponse(result)
            if isinstance(result, dict):
                return TestResponse(JSONResponse(result))
            return TestResponse(Response(result or ""))

        def get(self, path: str, params=None, auth=None):
            return self._handle("GET", path, params=params, auth=auth)

        def post(self, path: str, params=None, auth=None, data=None):
            return self._handle("POST", path, params=params, auth=auth, data=data)

    class FastAPI(APIRouter):
        def __init__(self, *args, **kwargs):
            super().__init__()
            self.routers = []

        def include_router(self, router: APIRouter):
            self.routers.append(router)

    class HTTPBasicCredentials:
        def __init__(self, username: str, password: str):
            self.username = username
            self.password = password

    class HTTPBasic:
        def __call__(self, request: Request) -> HTTPBasicCredentials:
            username = password = None
            if request.auth:
                username, password = request.auth
            elif "authorization" in {k.lower() for k in request.headers}:
                header_value = request.headers.get("Authorization") or request.headers.get("authorization")
                if header_value and header_value.startswith("Basic "):
                    encoded = header_value.split(" ", 1)[1]
                    decoded = base64.b64decode(encoded).decode()
                    username, password = decoded.split(":", 1)

            if username is None or password is None:
                raise HTTPException(
                    status_code=_Status.HTTP_401_UNAUTHORIZED,
                    detail="Not authenticated",
                    headers={"WWW-Authenticate": "Basic"},
                )
            return HTTPBasicCredentials(username=username, password=password)

    fastapi.HTTPException = HTTPException
    fastapi.Depends = Depends
    fastapi.Query = Query
    fastapi.Request = Request
    fastapi.Response = Response
    fastapi.HTMLResponse = HTMLResponse
    fastapi.JSONResponse = JSONResponse
    fastapi.RedirectResponse = RedirectResponse
    fastapi.APIRouter = APIRouter
    fastapi.FastAPI = FastAPI
    fastapi.status = status
    fastapi.security = types.SimpleNamespace(HTTPBasic=HTTPBasic, HTTPBasicCredentials=HTTPBasicCredentials)
    fastapi.responses = types.SimpleNamespace(HTMLResponse=HTMLResponse, JSONResponse=JSONResponse, RedirectResponse=RedirectResponse)

    templating = types.ModuleType("fastapi.templating")
    templating.Jinja2Templates = Jinja2Templates

    testclient = types.ModuleType("fastapi.testclient")
    testclient.TestClient = TestClient

    sys.modules["fastapi"] = fastapi
    sys.modules["fastapi.templating"] = templating
    sys.modules["fastapi.testclient"] = testclient
    sys.modules["fastapi.security"] = fastapi.security
    sys.modules["fastapi.responses"] = fastapi.responses
    sys.modules["starlette"] = types.SimpleNamespace(status=status)
    sys.modules["starlette.status"] = status


# Provide a minimal Typer stub when typer is unavailable.
try:  # pragma: no cover
    import typer  # noqa: F401
    from typer.testing import CliRunner  # noqa: F401
except ImportError:  # pragma: no cover
    import contextlib
    import inspect
    import io
    from types import SimpleNamespace

    typer = types.ModuleType("typer")

    class Exit(Exception):
        def __init__(self, code: int = 0):
            self.exit_code = code

    class BadParameter(Exception):
        pass

    class _Param:
        def __init__(self, default=None):
            self.default = default

    def echo(message: object, err: bool = False) -> None:
        output = str(message)
        if err:
            print(output, file=sys.stderr)
        else:
            print(output)

    def Option(default=None, *args, **kwargs):
        return _Param(default)

    def Argument(default=..., *args, **kwargs):
        return _Param(default if default is not ... else None)

    class Typer:
        def __init__(self, *args, **kwargs):
            self.commands = {}

        def command(self, name: str):
            def decorator(func):
                self.commands[name] = func
                return func

            return decorator

        def add_typer(self, typer_obj, name: str):
            self.commands[name] = typer_obj

    def _convert(value, annotation):
        if annotation is int:
            try:
                return int(value)
            except Exception:
                return value
        return value

    class _CliRunnerResult:
        def __init__(self, exit_code: int, stdout: str):
            self.exit_code = exit_code
            self.stdout = stdout

    class _Invoker:
        def __init__(self, app):
            self.app = app

        def _call(self, func, args):
            sig = inspect.signature(func)
            params = list(sig.parameters.values())
            positional_params = [p for p in params if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)]
            kwargs: dict[str, object] = {}
            collected_args: list[object] = []
            iterator = iter(args)
            for raw in iterator:
                if raw.startswith("--"):
                    name = raw.lstrip("-").replace("-", "_")
                    try:
                        value = next(iterator)
                    except StopIteration:
                        value = None
                    param = sig.parameters.get(name)
                    kwargs[name] = _convert(value, param.annotation if param else None)
                else:
                    collected_args.append(raw)
            for param, value in zip(positional_params, collected_args):
                kwargs[param.name] = _convert(value, param.annotation)
            for param in params:
                if param.name in kwargs:
                    continue
                default = param.default
                if isinstance(default, _Param):
                    default = default.default
                if default is inspect._empty:
                    default = None
                kwargs[param.name] = default
            return func(**kwargs)

        def _dispatch(self, app, args):
            if not args:
                raise Exit(code=1)
            command = args[0]
            target = app.commands.get(command)
            if target is None:
                raise Exit(code=1)
            if isinstance(target, Typer):
                if len(args) < 2:
                    raise Exit(code=1)
                return self._dispatch(target, args[1:])
            return self._call(target, args[1:])

        def invoke(self, args):
            try:
                return self._dispatch(self.app, args)
            except Exit as exc:
                raise exc

    class CliRunner:
        def invoke(self, app, args):
            buffer = io.StringIO()
            exit_code = 0
            try:
                with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
                    invoker = _Invoker(app)
                    invoker.invoke(args)
            except Exit as exc:
                exit_code = exc.exit_code
            except BadParameter as exc:
                exit_code = 2
                print(str(exc), file=buffer)
            stdout = buffer.getvalue()
            return _CliRunnerResult(exit_code, stdout)

    typer.BadParameter = BadParameter
    typer.Exit = Exit
    typer.Option = Option
    typer.Argument = Argument
    typer.echo = echo
    typer.Typer = Typer

testing = types.ModuleType("typer.testing")
testing.CliRunner = CliRunner

sys.modules["typer"] = typer
sys.modules["typer.testing"] = testing


@pytest.fixture(autouse=True)
def reset_settings_cache():
    """Ensure cached settings do not leak across tests when env vars change."""

    try:
        from app import config as app_config

        app_config.get_settings.cache_clear()
    except Exception:  # pragma: no cover - defensive
        pass
    yield
    try:
        app_config.get_settings.cache_clear()
    except Exception:  # pragma: no cover - defensive
        pass



