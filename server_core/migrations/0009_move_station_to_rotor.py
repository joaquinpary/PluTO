from django.db import migrations


def copy_station_to_rotor(apps, schema_editor):
    """The location moves from the plugin instance to its board (spec 5.2).

    A board that already has a location keeps it, and when several instances
    share a board the oldest one wins. An instance without a board has nowhere
    to put its location and loses it, and so does one still at (0, 0): that was
    the default, not a place anybody measured.
    """
    PluginInstance = apps.get_model('server_core', 'PluginInstance')
    Rotor = apps.get_model('server_core', 'Rotor')
    for plugin in PluginInstance.objects.exclude(rotor=None).order_by('pk'):
        if plugin.station_lat == 0 and plugin.station_lon == 0:
            continue
        # Filtering on the empty location re-reads the row, so the first
        # instance of a shared board is the one that sets it.
        Rotor.objects.filter(pk=plugin.rotor_id, latitude_deg=None, longitude_deg=None).update(
            latitude_deg=plugin.station_lat,
            longitude_deg=plugin.station_lon,
            altitude_m=plugin.station_alt,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('server_core', '0008_rotor_location'),
    ]

    operations = [
        migrations.RunPython(copy_station_to_rotor, migrations.RunPython.noop),
        migrations.RemoveField(model_name='plugininstance', name='station_alt'),
        migrations.RemoveField(model_name='plugininstance', name='station_lat'),
        migrations.RemoveField(model_name='plugininstance', name='station_lon'),
    ]
