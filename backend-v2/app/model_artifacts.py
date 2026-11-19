import re

_OBJECT_KEY = re.compile(r'[A-Za-z0-9_-][A-Za-z0-9_.-]*(?:/[A-Za-z0-9_-][A-Za-z0-9_.-]*)*')


def within_namespace(key: str, namespace: str) -> bool:
    return bool(_OBJECT_KEY.fullmatch(namespace) and _OBJECT_KEY.fullmatch(key)
                and key.startswith(namespace + '/'))
