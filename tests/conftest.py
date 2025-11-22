from datetime import datetime, timezone
from pathlib import Path
import sys
import types

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


# Provide a minimal pydantic_settings stub so tests do not require the real
# dependency.
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


# Provide a lightweight FastAPI stub when the dependency is unavailable.
if "fastapi" not in sys.modules:  # pragma: no cover
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

    def DependsStub(dep):
        return Depends(dep)

    def QueryStub(default=...):
        return Query(default)

    def _match_route(path: str, route_path: str):
        path_parts = [p for p in path.split("/") if p]
        route_parts = [p for p in route_path.split("/") if p]
        if len(path_parts) != len(route_parts):
            return None
        params = {}
        for part, route_part in zip(path_parts, route_parts):
            if route_part.startswith("{") and route_part.endswith("}"):
                params[route_part.strip("{}")]=part
            elif part != route_part:
                return None
        return params

    def _resolve_dependencies(func, request: Request, path_params: dict, query_params: dict):
        kwargs = {}
        sig = inspect.signature(func)
        for name, param in sig.parameters.items():
            if name == "request":
                kwargs[name] = request
                continue
            default = param.default
            if isinstance(default, Query):
                if name in query_params:
                    value = query_params[name]
                elif default.default is ...:
                    raise HTTPException(_Status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Missing parameter")
                else:
                    value = default.default
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
        def __init__(self, app: FastAPI):
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

    fastapi.FastAPI = FastAPI
    fastapi.APIRouter = APIRouter
    fastapi.Depends = DependsStub
    fastapi.Query = QueryStub
    fastapi.HTTPException = HTTPException
    fastapi.status = status
    fastapi.Request = Request
    fastapi.responses = types.SimpleNamespace(
        HTMLResponse=HTMLResponse,
        JSONResponse=JSONResponse,
        RedirectResponse=RedirectResponse,
        Response=Response,
    )
    sys.modules["fastapi"] = fastapi

    responses_mod = types.ModuleType("fastapi.responses")
    responses_mod.HTMLResponse = HTMLResponse
    responses_mod.JSONResponse = JSONResponse
    responses_mod.RedirectResponse = RedirectResponse
    responses_mod.Response = Response
    sys.modules["fastapi.responses"] = responses_mod

    templating_mod = types.ModuleType("fastapi.templating")
    templating_mod.Jinja2Templates = Jinja2Templates
    sys.modules["fastapi.templating"] = templating_mod

    security_mod = types.ModuleType("fastapi.security")
    security_mod.HTTPBasic = HTTPBasic
    security_mod.HTTPBasicCredentials = HTTPBasicCredentials
    sys.modules["fastapi.security"] = security_mod

    testclient_mod = types.ModuleType("fastapi.testclient")
    testclient_mod.TestClient = TestClient
    sys.modules["fastapi.testclient"] = testclient_mod



# Provide a small Typer stub when typer is unavailable to keep CLI tests
# lightweight.
if "typer" not in sys.modules:  # pragma: no cover
    typer = types.ModuleType("typer")
    typer_output: list[str] = []

    class BadParameter(Exception):
        pass

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
                    key = token.lstrip("-").replace("-", "_")
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
                        kwargs[param.name] = self._convert(options[param.name], param.annotation)
                        continue
                if param.name in options:
                    kwargs[param.name] = self._convert(options[param.name], param.annotation)

            try:
                return func(*bound_args, **kwargs)
            except BadParameter as exc:
                echo(str(exc))
                raise SystemExit(2)

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
    typer.BadParameter = BadParameter
    sys.modules["typer.testing"] = testing


# Provide lightweight feedparser/httpx stubs to keep network-facing code testable
# without external dependencies.
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

    class HTTPXResponse:
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

    httpx.Response = HTTPXResponse
    httpx.HTTPStatusError = HTTPStatusError
    httpx.codes = Codes()

    def _missing_get(*args, **kwargs):  # pragma: no cover
        return HTTPXResponse(status_code=200, text="")

    httpx.get = _missing_get
    sys.modules["httpx"] = httpx
