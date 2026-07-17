from typing import Any, ClassVar, cast

from pydantic import (
    AnyUrl,
    BaseModel,
    EmailStr,
    Field,
    FilePath,
    SecretStr,
    create_model,
)

_RESERVED = frozenset({"type", "description", "default"})


class SchemaBuilder:
    """YAML `{fields: {name: type|dict}}` -> Pydantic models for structured output.

    Field types: scalars (str/int/float/bool/list/dict), email/url/filepath/secret,
    list[<type>], another schema name, or trailing `?` for optional (null default).
    Dict fields: `{type, description?, default?, ...}` — extra keys pass to Field.
    """

    SCALARS: ClassVar[dict[str, Any]] = {
        "str": str,
        "int": int,
        "float": float,
        "list": list,
        "dict": dict,
        "bool": bool,
        "email": EmailStr,
        "url": AnyUrl,
        "filepath": FilePath,
        "secret": SecretStr,
    }

    def __init__(self, specs: dict[str, dict] | None = None):
        self.registry: dict[str, type[BaseModel]] = {}
        self._specs = dict(specs or {})
        self._building: set[str] = set()
        for name in self._specs:
            self._ensure(name)

    def _ensure(self, name: str) -> type[BaseModel]:
        if name in self.registry:
            return self.registry[name]
        if name in self._building:
            raise ValueError(f"Circular schema ref: {name}")
        self._building.add(name)
        self.registry[name] = self._create(name, self._specs[name]["fields"])
        self._building.discard(name)
        return self.registry[name]

    def _resolve_type(self, spec: str) -> Any:
        spec = spec.strip()
        if spec.startswith("list[") and spec.endswith("]"):
            inner = self._resolve_type(spec[5:-1])
            return list[inner]
        if spec.startswith("dict[") and spec.endswith("]"):
            inner = self._resolve_type(spec[5:-1])
            return dict[str, inner]
        if spec in self.SCALARS:
            return self.SCALARS[spec]
        if spec in self.registry:
            return self.registry[spec]
        if spec in self._specs:
            return self._ensure(spec)
        raise ValueError(f"Unknown type: {spec!r}")

    def _field(self, spec: str | dict) -> tuple[Any, Any]:
        if isinstance(spec, dict):
            typ = spec["type"]
            default = spec.get("default", ...)
            desc = spec.get("description")
            kwargs = {k: v for k, v in spec.items() if k not in _RESERVED}
        else:
            typ, default, desc, kwargs = spec, ..., None, {}

        optional = typ.endswith("?")
        py_type = self._resolve_type(typ.rstrip("?"))
        if optional:
            py_type, default = py_type | None, None if default is ... else default

        if desc or kwargs:
            return py_type, Field(default, description=desc, **kwargs)
        return py_type, default

    def _create(self, name: str, fields: dict[str, str | dict]) -> type[BaseModel]:
        defs = {k: self._field(v) for k, v in fields.items()}
        return create_model(name, **cast(Any, defs))

    def output_schema(self, spec: str | dict) -> type[BaseModel]:
        if isinstance(spec, str):
            return self.registry[spec]
        return self._create(spec.get("name", "Output"), spec["fields"])
