"""Offline conversion of Buffer's official reference markdown to a validation schema.

Usage: python scripts/schema_from_reference.py reference.md output.graphql
This is a docs-derived snapshot, NOT authenticated server introspection.
"""
from pathlib import Path
import re
import sys


def convert(source):
    parts = []
    for section in re.split(r'^## ', source, flags=re.M)[1:]:
        group = section.split('\n', 1)[0].strip()
        entries = re.split(r'^#### ', section, flags=re.M)[1:]
        if group in ('Queries', 'Mutations'):
            fields = []
            for entry in entries:
                name = entry.split('\n', 1)[0].strip()
                result = re.search(r'\*\*Returns:\*\* `([^`]+)`', entry).group(1)
                args = re.findall(r'^- `([^`]+)`: `([^`]+)`', entry, flags=re.M)
                signature = '(' + ', '.join(n + ': ' + t for n, t in args) + ')' if args else ''
                fields.append(name + signature + ': ' + result)
            parts.append('type ' + ('Query' if group == 'Queries' else 'Mutation') + ' {\n' + '\n'.join(fields) + '\n}')
            continue
        for entry in entries:
            name = entry.split('\n', 1)[0].strip()
            fields = re.findall(r'^- `([^`]+)`: `([^`]+)`([^\n]*)', entry, flags=re.M)
            if group == 'Scalars':
                parts.append('scalar ' + name)
            elif group == 'Enums':
                values = re.findall(r'^- `([^`]+)`', entry, flags=re.M)
                parts.append('enum ' + name + ' { ' + ' '.join(values) + ' }')
            elif group == 'Unions':
                types = re.search(r'\*\*Possible types:\*\* ([^\n]+)', entry).group(1)
                parts.append('union ' + name + ' = ' + types)
            elif fields:
                kind = 'input' if group == 'Input Types' else 'interface' if group == 'Interfaces' else 'type'
                implements = re.search(r'\*\*Implements:\*\* ([^\n]+)', entry)
                spec = ' implements ' + implements.group(1).replace(', ', ' & ') if implements else ''
                lines = []
                for field, field_type, extra in fields:
                    default = re.match(r' \(default: ([^)]+)\)', extra)
                    suffix = ' = ' + default.group(1) if default and kind == 'input' else ''
                    lines.append(field + ': ' + field_type + suffix)
                parts.append(kind + ' ' + name + spec + ' {\n' + '\n'.join(lines) + '\n}')
    return '# Derived from https://developers.buffer.com/reference.md on 2026-10-09\n' + '\n\n'.join(parts)


if __name__ == '__main__':
    Path(sys.argv[2]).write_text(convert(Path(sys.argv[1]).read_text()), encoding='utf-8')
