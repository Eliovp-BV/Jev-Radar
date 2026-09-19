"""Adapt application JSON schemas to the strict structured-output contract.

The application still validates replies with its Pydantic model. Strict provider
output prevents missing/extra fields and wrong enum values before that boundary.
"""
from copy import deepcopy


def strict_schema(schema):
    result = deepcopy(schema)

    def visit(node):
        if not isinstance(node, dict):
            return
        node.pop('default', None)
        if 'const' in node:
            value = node.pop('const')
            node['enum'] = [value]
            if 'type' not in node:
                node['type'] = ('null' if value is None else 'boolean' if isinstance(value, bool)
                                else 'integer' if isinstance(value, int) else 'number' if isinstance(value, float)
                                else 'string')
        if node.get('type') == 'object' or 'properties' in node:
            properties = node.setdefault('properties', {})
            node['required'] = list(properties)
            node['additionalProperties'] = False
        for key in ('$defs', 'definitions', 'properties'):
            for child in node.get(key, {}).values():
                visit(child)
        visit(node.get('items'))
        for key in ('anyOf', 'oneOf', 'allOf'):
            for child in node.get(key, []):
                visit(child)
    visit(result)
    if result.get('type') != 'object' or 'anyOf' in result:
        raise ValueError('Research output schema must describe a root object')
    return result
