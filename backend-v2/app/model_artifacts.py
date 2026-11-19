import re

_OBJECT_KEY = re.compile(r'[A-Za-z0-9_-][A-Za-z0-9_.-]*(?:/[A-Za-z0-9_-][A-Za-z0-9_.-]*)*')


def valid_object_key(key: str) -> bool:
    return bool(_OBJECT_KEY.fullmatch(key))


def within_namespace(key: str, namespace: str) -> bool:
    return bool(valid_object_key(namespace) and valid_object_key(key)
                and key.startswith(namespace + '/'))
