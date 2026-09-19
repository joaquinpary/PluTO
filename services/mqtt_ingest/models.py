"""MongoDB documents owned by the ingester.

The ingester is the only writer of this collection, so the schema lives here
rather than in the Django app. When something else needs to read it back --
the history views of HU-25, for instance -- that is the moment to lift these
into a shared contracts package.
"""
from datetime import datetime

import mongoengine


class GenericJSONDocument(mongoengine.DynamicDocument):
    """
    A generic dynamic document designed to store arbitrary JSON data.
    Because data is formatted as JSONs, DynamicDocument allows you to attach
    any fields dynamically, or you can use the 'payload' DictField to store the entire JSON.
    """
    meta = {'abstract': True}

    created_at = mongoengine.DateTimeField(default=datetime.utcnow)
    payload = mongoengine.DictField()


class PluginData(GenericJSONDocument):
    """Collection for plugin data (one document per ingested MQTT message)"""

    # Where the message came from
    plugin_id    = mongoengine.StringField(required=True)
    plugin_type  = mongoengine.StringField()
    device       = mongoengine.StringField()
    message_type = mongoengine.StringField(required=True)

    # How the payload was normalized by the plugin before publishing
    payload_format = mongoengine.StringField(default='json')
    schema_version = mongoengine.IntField(default=1)

    # Tracing: message_id correlates the plugin log line with this document,
    # received_at is when the plugin saw it and created_at when it was persisted
    message_id   = mongoengine.StringField()
    source_topic = mongoengine.StringField()
    ingest_topic = mongoengine.StringField()
    received_at  = mongoengine.DateTimeField()

    meta = {
        'collection': 'plugin_data',
        'indexes': [
            ('plugin_id', 'message_type', '-created_at'),
            ('device', '-created_at'),
        ],
        'ordering': ['-created_at'],
    }
