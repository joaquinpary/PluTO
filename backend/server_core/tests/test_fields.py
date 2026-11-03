from django.test import SimpleTestCase

from ..plugin_handlers import PLUGIN_HANDLERS, get_handler
from ..plugin_handlers.base import BasePluginHandler
from ..plugin_handlers.fields import (
    FIELD_TYPES, REQUIRED, apply_defaults, config_errors, config_field, validate_config,
)

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


class HandlerFieldsTests(SimpleTestCase):
    def test_get_handler(self):
        self.assertIs(get_handler('tinygs'), PLUGIN_HANDLERS['tinygs'])
        self.assertIsNone(get_handler('nope'))

    def test_every_type_has_a_label_and_well_formed_fields(self):
        for plugin_type, handler in PLUGIN_HANDLERS.items():
            with self.subTest(plugin_type=plugin_type):
                self.assertTrue(handler.label)
                for field in handler.config_fields:
                    self.assertEqual(set(field), FIELD_KEYS)
                    self.assertIn(field['type'], FIELD_TYPES)
                    # A default the form offers must pass the same checks.
                    if field['default'] is not None:
                        self.assertEqual(validate_config((field,), {field['name']: field['default']}), {})

    def test_tinygs_declares_the_fields_of_the_spec(self):
        fields = {field['name']: field for field in get_handler('tinygs').config_fields}

        self.assertEqual(list(fields), [
            'tinygs_device', 'tinygs_topic_prefix', 'min_elevation_deg',
            'lookahead_minutes', 'sample_seconds', 'tle_ttl_hours',
        ])
        self.assertTrue(fields['tinygs_device']['required'])
        self.assertEqual(
            {name: fields[name]['default'] for name in ('min_elevation_deg', 'lookahead_minutes', 'sample_seconds', 'tle_ttl_hours')},
            {'min_elevation_deg': 10, 'lookahead_minutes': 20, 'sample_seconds': 1, 'tle_ttl_hours': 12},
        )

    def test_file_tracker_declares_two_required_choices(self):
        fields = {field['name']: field for field in get_handler('file_tracker').config_fields}

        self.assertEqual(list(fields), ['coord_type', 'coord_format'])
        self.assertTrue(all(field['type'] == 'choice' and field['required'] for field in fields.values()))


class TinyGSConfigTests(SimpleTestCase):
    def errors(self, **config):
        return config_errors(get_handler('tinygs'), {'tinygs_device': 'My_TinyGS', **config})

    def test_a_plain_device_and_sensible_pass_settings_are_valid(self):
        self.assertEqual(self.errors(), {})
        self.assertEqual(self.errors(
            tinygs_topic_prefix='pluto', min_elevation_deg=15, lookahead_minutes=20, sample_seconds=1, tle_ttl_hours=12.5,
        ), {})

    def test_the_device_is_required_and_a_topic_safe_slug(self):
        for device in (None, '', '   ', '+', '#', 'heltec/lp-01', 'Estacion Cordoba', 'estación', 'a.b'):
            with self.subTest(device=device):
                self.assertIn('tinygs_device', self.errors(tinygs_device=device))

    def test_the_topic_prefix_is_a_single_segment(self):
        for prefix in ('pluto/extra', '+', '#', ' '):
            with self.subTest(prefix=prefix):
                self.assertIn('tinygs_topic_prefix', self.errors(tinygs_topic_prefix=prefix))

    def test_impossible_pass_settings_are_rejected(self):
        for key, value in (
            ('min_elevation_deg', 91),
            ('min_elevation_deg', -91),
            ('lookahead_minutes', 0),
            ('sample_seconds', -1),
            ('sample_seconds', 0),
            ('tle_ttl_hours', 0),
            ('sample_seconds', '1'),
            ('lookahead_minutes', True),
        ):
            with self.subTest(key=key, value=value):
                self.assertIn(key, self.errors(**{key: value}))


class FileTrackerConfigTests(SimpleTestCase):
    def errors(self, **config):
        return config_errors(get_handler('file_tracker'), config)

    def test_the_five_valid_combinations(self):
        for coord_type, coord_format in (
            ('ECEF', 'CARTESIAN'), ('ECEF', 'GEO'), ('ECI', 'CARTESIAN'), ('ENU', 'POLAR'), ('ENU', 'CARTESIAN'),
        ):
            with self.subTest(coord_type=coord_type, coord_format=coord_format):
                self.assertEqual(self.errors(coord_type=coord_type, coord_format=coord_format), {})

    def test_any_other_combination_is_a_cross_field_error(self):
        self.assertEqual(list(self.errors(coord_type='ENU', coord_format='GEO')), ['non_field_errors'])

    def test_both_are_required_choices(self):
        self.assertEqual(self.errors(), {'coord_type': [REQUIRED], 'coord_format': [REQUIRED]})
        self.assertIn('coord_type', self.errors(coord_type='XYZ', coord_format='GEO'))
