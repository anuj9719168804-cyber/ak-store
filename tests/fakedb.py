"""Minimal in-memory stand-in for a Motor database, just enough for the v9 modules' tests.

Supports: find_one / find (sort, skip, limit, to_list, async-iter) / insert_one / update_one /
update_many / find_one_and_update / delete_one / delete_many / count_documents / aggregate($group,
$match, $sort, $limit) / create_index (no-op) with the filter and update operators the code uses.
"""
import copy
import itertools
import re
from types import SimpleNamespace

_missing = object()


def _get(doc, path, default=_missing):
    cur = doc
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur


def _cmp(value, op, arg):
    if op == "$eq":
        return value == arg
    if op == "$ne":
        return value != arg
    if op == "$exists":
        return (value is not _missing) == bool(arg)
    if value is _missing:
        return op in ("$nin",)
    if op == "$gt":
        return value is not None and value > arg
    if op == "$gte":
        return value is not None and value >= arg
    if op == "$lt":
        return value is not None and value < arg
    if op == "$lte":
        return value is not None and value <= arg
    if op == "$in":
        return value in arg
    if op == "$nin":
        return value not in arg
    if op == "$regex":
        return isinstance(value, str) and re.search(arg, value) is not None
    if op == "$options":
        return True
    if op == "$type":
        return True
    raise NotImplementedError(op)


def matches(doc, flt):
    for key, cond in flt.items():
        if key == "$or":
            if not any(matches(doc, f) for f in cond):
                return False
        elif key == "$and":
            if not all(matches(doc, f) for f in cond):
                return False
        else:
            value = _get(doc, key)
            if isinstance(cond, dict) and cond and all(k.startswith("$") for k in cond):
                opts = cond.get("$options", "")
                for op, arg in cond.items():
                    if op == "$regex" and "i" in opts:
                        arg = "(?i)" + arg
                    if not _cmp(value, op, arg):
                        return False
            else:
                if value is _missing:
                    if cond is not None:
                        return False
                elif value != cond:
                    return False
    return True


def _apply(doc, update, inserting=False):
    for op, fields in update.items():
        for key, val in fields.items():
            if op == "$set":
                doc[key] = copy.deepcopy(val)
            elif op == "$unset":
                doc.pop(key, None)
            elif op == "$inc":
                cur = doc.get(key, 0)
                doc[key] = (cur or 0) + val
            elif op == "$setOnInsert":
                if inserting:
                    doc[key] = copy.deepcopy(val)
            elif op == "$addToSet":
                doc.setdefault(key, [])
                if val not in doc[key]:
                    doc[key].append(val)
            elif op == "$pull":
                doc[key] = [x for x in doc.get(key, []) if x != val]
            else:
                raise NotImplementedError(op)


class Cursor:
    def __init__(self, docs):
        self.docs = docs

    def sort(self, spec, direction=None):
        if isinstance(spec, str):
            spec = [(spec, direction or 1)]
        for key, d in reversed(spec):
            self.docs.sort(key=lambda x, k=key: (_get(x, k, None) is None, _get(x, k, None)), reverse=(d == -1))
        return self

    def skip(self, n):
        self.docs = self.docs[n:]
        return self

    def limit(self, n):
        self.docs = self.docs[:n] if n else self.docs
        return self

    async def to_list(self, length=None):
        return [copy.deepcopy(d) for d in (self.docs if length is None else self.docs[:length])]

    def __aiter__(self):
        self._it = iter([copy.deepcopy(d) for d in self.docs])
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class Collection:
    def __init__(self):
        self.docs = []
        self._ids = itertools.count(1)

    async def find_one(self, flt=None, projection=None):
        for d in self.docs:
            if matches(d, flt or {}):
                return copy.deepcopy(d)
        return None

    def find(self, flt=None, projection=None):
        return Cursor([d for d in self.docs if matches(d, flt or {})])

    async def insert_one(self, doc):
        doc = copy.deepcopy(doc)
        doc.setdefault("_id", next(self._ids))
        if any(d["_id"] == doc["_id"] for d in self.docs):
            raise RuntimeError("duplicate key")
        self.docs.append(doc)
        return SimpleNamespace(inserted_id=doc["_id"])

    async def update_one(self, flt, update, upsert=False):
        for d in self.docs:
            if matches(d, flt):
                before = copy.deepcopy(d)
                _apply(d, update)
                return SimpleNamespace(matched_count=1, modified_count=int(before != d), upserted_id=None)
        if upsert:
            new = {k: v for k, v in flt.items() if not k.startswith("$") and not isinstance(v, dict)}
            _apply(new, update, inserting=True)
            new.setdefault("_id", next(self._ids))
            self.docs.append(new)
            return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=new["_id"])
        return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=None)

    async def update_many(self, flt, update):
        n = 0
        for d in self.docs:
            if matches(d, flt):
                _apply(d, update)
                n += 1
        return SimpleNamespace(matched_count=n, modified_count=n)

    async def find_one_and_update(self, flt, update, upsert=False, return_document=False):
        for d in self.docs:
            if matches(d, flt):
                before = copy.deepcopy(d)
                _apply(d, update)
                return copy.deepcopy(d) if return_document else before
        if upsert:
            new = {k: v for k, v in flt.items() if not k.startswith("$") and not isinstance(v, dict)}
            _apply(new, update, inserting=True)
            new.setdefault("_id", next(self._ids))
            self.docs.append(new)
            return copy.deepcopy(new) if return_document else None
        return None

    async def delete_one(self, flt):
        for i, d in enumerate(self.docs):
            if matches(d, flt):
                del self.docs[i]
                return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)

    async def delete_many(self, flt):
        keep = [d for d in self.docs if not matches(d, flt)]
        n = len(self.docs) - len(keep)
        self.docs = keep
        return SimpleNamespace(deleted_count=n)

    async def count_documents(self, flt=None):
        return sum(1 for d in self.docs if matches(d, flt or {}))

    async def create_index(self, *a, **k):
        return "idx"

    def aggregate(self, pipeline):
        docs = [copy.deepcopy(d) for d in self.docs]
        for stage in pipeline:
            if "$match" in stage:
                docs = [d for d in docs if matches(d, stage["$match"])]
            elif "$group" in stage:
                spec = stage["$group"]
                groups = {}
                for d in docs:
                    key_spec = spec["_id"]
                    key = None if key_spec is None else (_get(d, key_spec[1:], None) if isinstance(key_spec, str) else tuple(_get(d, v[1:], None) for v in key_spec.values()))
                    g = groups.setdefault(key, {"_id": key if not isinstance(key_spec, dict) else dict(zip(key_spec.keys(), key))})
                    for out, acc in spec.items():
                        if out == "_id":
                            continue
                        (op, arg), = acc.items()
                        if op == "$sum":
                            g[out] = g.get(out, 0) + (arg if isinstance(arg, int) else (_get(d, arg[1:], 0) or 0))
                        elif op == "$push":
                            g.setdefault(out, []).append(_get(d, arg[1:], None))
                        elif op == "$first":
                            g.setdefault(out, _get(d, arg[1:], None))
                docs = list(groups.values())
            elif "$sort" in stage:
                for key, d in reversed(list(stage["$sort"].items())):
                    docs.sort(key=lambda x, k=key: x.get(k) or 0, reverse=(d == -1))
            elif "$limit" in stage:
                docs = docs[: stage["$limit"]]
            else:
                raise NotImplementedError(stage)

        class _Agg:
            async def to_list(self, length=None):
                return docs if length is None else docs[:length]

            def __aiter__(self):
                self._it = iter(docs)
                return self

            async def __anext__(self):
                try:
                    return next(self._it)
                except StopIteration:
                    raise StopAsyncIteration
        return _Agg()


class FakeDB:
    """db['name'] and db.name both give a Collection (created on first use)."""

    def __init__(self):
        self._cols = {}

    def __getitem__(self, name):
        return self._cols.setdefault(name, Collection())

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self[name]
