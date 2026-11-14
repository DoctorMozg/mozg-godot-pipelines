"""String store under <project>/i18n: source records per namespace, translations per locale.

Each file is rewritten whole with keys sorted, so worktrees that add different keys merge cleanly.
Keys are unique across namespaces, since tr() looks a key up without one.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from l10nkit.contracts import Contract, Json

log = logging.getLogger(__name__)
I18N, CONFIG, SRC, LOCALES, EVENTS = "i18n", "l10n.json", "src", "locales", "events"
KEY_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")
LOCALE_PATTERN = re.compile(r"^[a-z]{2,3}(_[A-Z][a-z]{3})?(_[A-Z]{2}|_[0-9]{3})?$")
SOURCE_FIELDS = (
    *("source", "forms", "context", "note", "max_chars", "max_px"),
    *("placeholders", "markup", "screenshots", "tags", "dnt"),
)
TRANSLATION_FIELDS = ("text", "forms", "status", "source_hash", "by")


class StoreError(ValueError):
    """A store file is unreadable or a change is refused; the message names the file or key."""


def source_hash(record: Mapping[str, Json]) -> str:
    """What a translation translates: the source or forms and the context."""
    basis = {name: record[name] for name in ("source", "forms", "context") if name in record}
    text = json.dumps(basis, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


@dataclass
class Namespace:
    name: str
    strings: dict[str, dict[str, Json]]
    patterns: list[str] = field(default_factory=list)


@dataclass
class Catalog:
    namespace: str
    locale: str
    strings: dict[str, dict[str, Json]]


class Store:
    def __init__(self, project: Path) -> None:
        self.root = project / I18N
        self._sources = Contract.load("string")
        self._translations = Contract.load("string-translation")

    @classmethod
    def init(cls, project: Path, source_locale: str) -> Store:
        if not LOCALE_PATTERN.match(source_locale):
            raise StoreError(f"{source_locale!r} is not a Godot locale code such as en or pt_BR")
        store = cls(project)
        if (store.root / CONFIG).exists():
            raise StoreError(f"{store.root / CONFIG} exists already")
        # .gdignore keeps Godot from importing the records; build/ stays visible to it.
        for folder in (SRC, LOCALES, EVENTS):
            (store.root / folder).mkdir(parents=True, exist_ok=True)
            (store.root / folder / ".gdignore").touch()
        _write(store.root / CONFIG, {"source_locale": source_locale})
        log.info("store created at %s, source locale %s", store.root, source_locale)
        return store

    @property
    def source_locale(self) -> str:
        config = _read(self.root / CONFIG)
        locale = config.get("source_locale")
        if not isinstance(locale, str) or not LOCALE_PATTERN.match(locale):
            raise StoreError(f"{self.root / CONFIG}: source_locale must be a locale code")
        return locale

    def namespaces(self) -> dict[str, Namespace]:
        found: dict[str, Namespace] = {}
        for path in sorted((self.root / SRC).glob("*.json")):
            doc = self._checked(path, self._sources)
            if doc["namespace"] != path.stem:
                raise StoreError(
                    f"{path}: namespace {doc['namespace']!r} differs from the file name"
                )
            found[path.stem] = Namespace(path.stem, doc["strings"], doc.get("patterns", []))
        return found

    def locales(self) -> list[str]:
        folder = self.root / LOCALES
        return sorted(p.name for p in folder.iterdir() if p.is_dir()) if folder.is_dir() else []

    def catalog(self, locale: str, namespace: str) -> Catalog:
        path = self.root / LOCALES / locale / f"{namespace}.json"
        if not path.is_file():
            return Catalog(namespace, locale, {})
        doc = self._checked(path, self._translations)
        if (doc["namespace"], doc["locale"]) != (namespace, locale):
            raise StoreError(f"{path}: namespace or locale differs from the path")
        return Catalog(namespace, locale, doc["strings"])

    def find(self, key: str) -> Namespace:
        for namespace in self.namespaces().values():
            if key in namespace.strings:
                return namespace
        raise StoreError(f"no key {key!r}")

    def add(self, namespace: str, key: str, record: dict[str, Json]) -> None:
        if not KEY_PATTERN.match(key):
            raise StoreError(f"key {key!r} must start with a letter and use A-Z, 0-9, _ . or -")
        current = self.namespaces()
        owner = next((n.name for n in current.values() if key in n.strings), None)
        if owner is not None:
            raise StoreError(f"key {key!r} exists already in namespace {owner!r}")
        target = current.get(namespace, Namespace(namespace, {}))
        target.strings[key] = self._valid_source(namespace, key, record)
        self.save(target)
        log.info("added %s to %s", key, namespace)

    def edit(self, key: str, changes: Mapping[str, Json], clear: Sequence[str] = ()) -> None:
        namespace = self.find(key)
        record = dict(namespace.strings[key])
        # A string is plain or plural: setting one shape drops the other.
        for shape, other in (("source", "forms"), ("forms", "source")):
            if shape in changes:
                record.pop(other, None)
        record.update(changes)
        for name in clear:
            if name in ("source", "forms"):
                raise StoreError(f"{name} cannot be cleared; set the other shape instead")
            record.pop(name, None)
        namespace.strings[key] = self._valid_source(namespace.name, key, record)
        self.save(namespace)
        log.info("edited %s in %s", key, namespace.name)

    def remove(self, key: str) -> list[str]:
        """Drops the key and its translations; returns the locales that had one."""
        namespace = self.find(key)
        del namespace.strings[key]
        self.save(namespace)
        touched = []
        for locale in self.locales():
            catalog = self.catalog(locale, namespace.name)
            if catalog.strings.pop(key, None) is not None:
                self.save_catalog(catalog)
                touched.append(locale)
        log.info("removed %s from %s and %d locales", key, namespace.name, len(touched))
        return touched

    def save(self, namespace: Namespace) -> None:
        doc: dict[str, Json] = {"schema": "string/1", "namespace": namespace.name}
        if namespace.patterns:
            doc["patterns"] = sorted(namespace.patterns)
        doc["strings"] = {
            k: _ordered(namespace.strings[k], SOURCE_FIELDS) for k in sorted(namespace.strings)
        }
        self._write_checked(self.root / SRC / f"{namespace.name}.json", doc, self._sources)

    def save_catalog(self, catalog: Catalog) -> None:
        strings = {k: _ordered(v, TRANSLATION_FIELDS) for k, v in sorted(catalog.strings.items())}
        doc: dict[str, Json] = {
            "schema": "string-translation/1", "namespace": catalog.namespace,
            "locale": catalog.locale, "strings": strings,
        }  # fmt: skip
        path = self.root / LOCALES / catalog.locale / f"{catalog.namespace}.json"
        self._write_checked(path, doc, self._translations)

    def _valid_source(self, namespace: str, key: str, record: dict[str, Json]) -> dict[str, Json]:
        if "source" in record and "forms" in record:
            raise StoreError(f"{key}: give source or forms, not both")
        doc = {"schema": "string/1", "namespace": namespace, "strings": {key: record}}
        if errors := self._sources.errors(doc):
            raise StoreError(f"{key}: " + "; ".join(errors))
        return record

    def _checked(self, path: Path, contract: Contract) -> dict[str, Json]:
        doc = _read(path)
        if errors := contract.errors(doc):
            raise StoreError(f"{path}: " + "; ".join(errors[:5]))
        return doc

    def _write_checked(self, path: Path, doc: dict[str, Json], contract: Contract) -> None:
        if errors := contract.errors(doc):
            raise StoreError(f"{path}: refusing to write: " + "; ".join(errors[:5]))
        path.parent.mkdir(parents=True, exist_ok=True)
        _write(path, doc)


def _ordered(record: Mapping[str, Json], fields: Sequence[str]) -> dict[str, Json]:
    return {name: record[name] for name in fields if name in record}


def _read(path: Path) -> dict[str, Json]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise StoreError(f"no {path}; run l10nkit init first") from error
    except (OSError, ValueError) as error:
        raise StoreError(f"cannot read {path}: {error}") from error
    if not isinstance(doc, dict):
        raise StoreError(f"{path}: expected a JSON object")
    return doc


def _write(path: Path, doc: Mapping[str, Json]) -> None:
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
