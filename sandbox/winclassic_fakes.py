"""Test helper for the winclassic tests: WinReg kept in a dict instead of the
registry, so no test ever writes to this machine."""


class MemoryRegistry:
    """Same methods as winclassic.WinReg, case-insensitive like the real one."""

    def __init__(self):
        # (hive, lowercase path) -> (path as written, {lowercase name: (name, type, data)})
        self._keys = {}

    def _values(self, hive, path):
        try:
            return self._keys[(hive, path.lower())][1]
        except KeyError:
            raise FileNotFoundError(f"{hive}\\{path}") from None

    def exists(self, hive, path):
        return (hive, path.lower()) in self._keys

    def create_key(self, hive, path):
        parts = path.split("\\")
        for i in range(1, len(parts) + 1):
            here = "\\".join(parts[:i])
            self._keys.setdefault((hive, here.lower()), (here, {}))

    def values(self, hive, path):
        return list(self._values(hive, path).values())

    def subkeys(self, hive, path):
        self._values(hive, path)
        prefix = path.lower() + "\\"
        return [written.rsplit("\\", 1)[-1]
                for (h, low), (written, _vals) in self._keys.items()
                if h == hive and low.startswith(prefix) and "\\" not in low[len(prefix):]]

    def get(self, hive, path, name):
        try:
            return self._values(hive, path)[name.lower()][1:]
        except KeyError:
            raise FileNotFoundError(f"{hive}\\{path}\\{name}") from None

    def set(self, hive, path, name, typ, data):
        self.create_key(hive, path)
        self._values(hive, path)[name.lower()] = (name, typ, data)

    def delete_tree(self, hive, path):
        self._values(hive, path)
        low = path.lower()
        for key in [k for k in self._keys
                    if k[0] == hive and (k[1] == low or k[1].startswith(low + "\\"))]:
            del self._keys[key]
