from django.test import SimpleTestCase

from .plugin_handlers.base import BasePluginHandler
from .plugin_handlers.fields import REQUIRED, apply_defaults, config_errors, config_field, validate_config

FIELD_KEYS = {'name', 'label', 'help', 'type', 'required', 'default', 'min', 'max', 'choices', 'pattern'}


class ConfigFieldTests(SimpleTestCase):
    def test_every_key_is_present(self):
        field = config_field('gain', 'Ganancia', 'number', min=0)

        self.assertEqual(set(field), FIELD_KEYS)
        self.assertEqual((field['type'], field['min'], field['max'], field['required']), ('number', 0, None, False))

    def test_a_typo_in_a_declaration_is_caught_at_once(self):
        with self.assertRaises(ValueError):
            config_field('gain', 'Ganancia', 'number', minimum=0)
        with self.assertRaises(ValueError):
            config_field('gain', 'Ganancia', 'float')


class ValidateConfigTests(SimpleTestCase):
    def errors(self, field, value):
        return validate_config((field,), {field['name']: value})

    def test_a_required_field_must_be_there(self):
        field = config_field('device', 'Dispositivo', 'string', required=True)

        for config in ({}, {'device': None}, {'device': ''}):
            with self.subTest(config=config):
                self.assertEqual(validate_config((field,), config), {'device': [REQUIRED]})

    def test_an_optional_field_may_be_missing_or_empty(self):
        field = config_field('prefix', 'Prefijo', 'string', pattern=r'[a-z]+')

        for config in ({}, {'prefix': None}, {'prefix': ''}):
            with self.subTest(config=config):
                self.assertEqual(validate_config((field,), config), {})

    def test_a_string_must_match_the_whole_pattern(self):
        field = config_field('device', 'Dispositivo', 'string', pattern=r'[a-z]+')

        self.assertEqual(self.errors(field, 'heltec'), {})
        for value in ('heltec 01', 'Heltec', 42):
            with self.subTest(value=value):
                self.assertIn('device', self.errors(field, value))

    def test_a_number_and_its_inclusive_range(self):
        field = config_field('elevation', 'Elevación', 'number', min=-90, max=90)

        for value in (-90, 0, 12.5, 90):
            with self.subTest(value=value):
                self.assertEqual(self.errors(field, value), {})
        for value in (-90.5, 91, '10', True):
            with self.subTest(value=value):
                self.assertIn('elevation', self.errors(field, value))

    def test_an_integer_is_a_whole_number(self):
        field = config_field('retries', 'Reintentos', 'integer', min=0)

        self.assertEqual(self.errors(field, 3), {})
        for value in (2.5, -1, False):
            with self.subTest(value=value):
                self.assertIn('retries', self.errors(field, value))

    def test_a_boolean_is_true_or_false(self):
        field = config_field('verbose', 'Detallado', 'boolean')

        self.assertEqual(self.errors(field, False), {})
        for value in (0, 'true'):
            with self.subTest(value=value):
                self.assertIn('verbose', self.errors(field, value))

    def test_a_choice_is_one_of_its_values(self):
        field = config_field('coord_type', 'Sistema', 'choice', choices=[['ECEF', 'ECEF'], ['ENU', 'ENU']])

        self.assertEqual(self.errors(field, 'ENU'), {})
        for value in ('enu', 'ECI'):
            with self.subTest(value=value):
                self.assertIn('coord_type', self.errors(field, value))

    def test_every_broken_field_is_reported(self):
        fields = (config_field('a', 'A', 'integer', required=True), config_field('b', 'B', 'boolean'))

        self.assertEqual(set(validate_config(fields, {'b': 'yes'})), {'a', 'b'})

    def test_keys_nobody_declared_are_left_alone(self):
        self.assertEqual(validate_config((), {'legacy': 1}), {})


class ApplyDefaultsTests(SimpleTestCase):
    def test_fills_what_is_missing_and_keeps_what_was_given(self):
        fields = (
            config_field('elevation', 'Elevación', 'number', default=10),
            config_field('lookahead', 'Anticipación', 'number', default=20),
            config_field('prefix', 'Prefijo', 'string'),
        )
        config = {'lookahead': 0, 'other': 'x'}

        self.assertEqual(apply_defaults(fields, config), {'elevation': 10, 'lookahead': 0, 'other': 'x'})
        self.assertEqual(config, {'lookahead': 0, 'other': 'x'})

    def test_none_counts_as_missing(self):
        fields = (config_field('elevation', 'Elevación', 'number', default=10),)

        self.assertEqual(apply_defaults(fields, {'elevation': None}), {'elevation': 10})


class PairHandler(BasePluginHandler):
    label = 'Par'
    config_fields = (
        config_field('low', 'Bajo', 'number', required=True),
        config_field('high', 'Alto', 'number', required=True),
    )

    def validate(self, config):
        return 'low must not exceed high.' if config['low'] > config['high'] else None


class ConfigErrorsTests(SimpleTestCase):
    def test_the_fields_come_first_and_spare_validate_a_broken_config(self):
        # validate() reads config['high'] without checking: it may take every field as valid.
        self.assertEqual(config_errors(PairHandler(), {'low': 1}), {'high': [REQUIRED]})

    def test_a_rule_across_fields_is_a_non_field_error(self):
        self.assertEqual(config_errors(PairHandler(), {'low': 5, 'high': 1}), {'non_field_errors': ['low must not exceed high.']})

    def test_a_valid_config_has_no_errors(self):
        self.assertEqual(config_errors(PairHandler(), {'low': 1, 'high': 5}), {})

    def test_a_config_must_be_an_object(self):
        for config in (None, [], 'x'):
            with self.subTest(config=config):
                self.assertEqual(config_errors(PairHandler(), config), {'non_field_errors': ['The configuration must be a JSON object.']})
