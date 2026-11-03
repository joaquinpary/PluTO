"""The settings a plugin type declares, and the checks they imply.

A handler lists its settings in config_fields. The front end builds the form
from them, and validate_config applies the same rules when the configuration is
saved, so a mistake shows up next to its field instead of when the container
starts. Rules that relate several settings stay in the handler's validate().
"""
import re

FIELD_TYPES = ('string', 'integer', 'number', 'boolean', 'choice')

REQUIRED = 'This field is required.'

# Every key a field carries besides name, label and type, with its value when unset.
_OPTIONS = {'help': '', 'required': False, 'default': None, 'min': None, 'max': None, 'choices': None, 'pattern': None}


def config_field(name, label, field_type, **options):
    """One entry of config_fields, with every key present so the API always sends the same shape."""
    if field_type not in FIELD_TYPES or not set(options) <= set(_OPTIONS):
        raise ValueError(f'Bad declaration of the config field {name!r}.')
    return {'name': name, 'label': label, 'type': field_type, **_OPTIONS, **options}


def apply_defaults(fields, config):
    """A copy of config with the default of every declared field it leaves out or sets to None."""
    result = dict(config)
    for field in fields:
        if field['default'] is not None and result.get(field['name']) is None:
            result[field['name']] = field['default']
    return result


def _is_number(value):
    # bool is an int in Python, and true is not a number of minutes.
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _field_errors(field, value):
    kind = field['type']
    if kind == 'string':
        if not isinstance(value, str):
            return ['Must be text.']
        if field['pattern'] and not re.fullmatch(field['pattern'], value):
            return [f'Must match {field["pattern"]}.']
        return []
    if kind == 'boolean':
        return [] if isinstance(value, bool) else ['Must be true or false.']
    if kind == 'choice':
        values = [choice[0] for choice in field['choices']]
        return [] if value in values else [f'Must be one of {", ".join(str(v) for v in values)}.']

    if not _is_number(value):
        return ['Must be a number.']
    if kind == 'integer' and not isinstance(value, int):
        return ['Must be a whole number.']
    if field['min'] is not None and value < field['min']:
        return [f'Must be at least {field["min"]}.']
    if field['max'] is not None and value > field['max']:
        return [f'Must be at most {field["max"]}.']
    return []


def validate_config(fields, config):
    """{name: [messages]} for every declared field config breaks; {} when it is valid.

    None and '' count as missing, which only a required field minds. Keys no
    field declares are left alone.
    """
    errors = {}
    for field in fields:
        value = config.get(field['name'])
        if value is None or value == '':
            if field['required']:
                errors[field['name']] = [REQUIRED]
            continue
        messages = _field_errors(field, value)
        if messages:
            errors[field['name']] = messages
    return errors


def config_errors(handler, config):
    """Everything wrong with config for this plugin type, as a DRF-style error dict.

    The declared fields first; the handler's validate() only once they pass,
    so it may take every field as valid. Its message goes under non_field_errors.
    """
    if not isinstance(config, dict):
        return {'non_field_errors': ['The configuration must be a JSON object.']}
    errors = validate_config(handler.config_fields, config)
    if errors:
        return errors
    error = handler.validate(config)
    return {'non_field_errors': [error]} if error else {}
