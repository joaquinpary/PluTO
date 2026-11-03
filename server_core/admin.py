from django import forms
from django.contrib import admin, messages

from . import lifecycle
from .models import DispatchOrder, PluginInstance, Rotor, RotorState
from .orchestrator import PluginOrchestrator


class PluginInstanceForm(forms.ModelForm):
    coordinates_file = forms.FileField(
        required=False,
        help_text=(
            'file_tracker only. Sent to the plugin when you save, running or not: a '
            'running plugin publishes it right away, a stopped one when it is launched. '
            'A new file replaces the previous one.'
        ),
    )

    class Meta:
        model = PluginInstance
        fields = '__all__'


@admin.register(PluginInstance)
class PluginInstanceAdmin(admin.ModelAdmin):
    form = PluginInstanceForm
    actions = ['launch_selected_plugins', 'stop_selected_plugins', 'sync_container_statuses']
    list_display  = ('name', 'plugin_type', 'status', 'runtime_status', 'rotor', 'container_id', 'updated_at')
    list_filter   = ('plugin_type', 'status')
    search_fields = ('name', 'container_id')
    readonly_fields = ('runtime_status', 'container_id', 'created_at', 'updated_at')

    add_fieldsets = [
        (
            None,
            {'fields': ('name', 'plugin_type')},
        ),
        (
            'Rotor',
            {
                'fields': ('rotor',),
                'description': (
                    'The rotor this instance points while it runs. Leave it empty for a '
                    'plugin that only produces data. A rotor is driven by one running '
                    'instance at a time, so assigning it here is what gives this plugin '
                    'exclusive control of the motors.'
                ),
            },
        ),
        (
            'Plugin Configuration',
            {
                'fields': ('config', 'coordinates_file'),
                'description': (
                    'Plugin-specific parameters as a JSON object. '
                    'These are passed directly to the orchestrator when launching. '
                    'Example for file_tracker: '
                    '{"coord_type": "ECEF", "coord_format": "GEO"}'
                ),
            },
        ),
        (
            'Metadata',
            {'fields': (), 'classes': ('collapse',)},
        ),
    ]

    change_fieldsets = [
        (
            None,
            {'fields': ('name', 'plugin_type', 'status', 'runtime_status', 'container_id')},
        ),
        (
            'Rotor',
            {
                'fields': ('rotor',),
                'description': (
                    'The rotor this instance points while it runs. Leave it empty for a '
                    'plugin that only produces data. A rotor is driven by one running '
                    'instance at a time, so assigning it here is what gives this plugin '
                    'exclusive control of the motors.'
                ),
            },
        ),
        (
            'Plugin Configuration',
            {
                'fields': ('config', 'coordinates_file'),
                'description': (
                    'Plugin-specific parameters as a JSON object. '
                    'These are passed directly to the orchestrator when launching. '
                    'Example for file_tracker: '
                    '{"coord_type": "ECEF", "coord_format": "GEO"}'
                ),
            },
        ),
        (
            'Metadata',
            {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)},
        ),
    ]

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return self.add_fieldsets
        return self.change_fieldsets

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = list(super().get_readonly_fields(request, obj))
        if obj is not None:
            # Changing the type of a running instance orphaned its container.
            readonly_fields += ['status', 'plugin_type']
        return tuple(readonly_fields)

    @admin.display(description='Docker status')
    def runtime_status(self, obj):
        if not obj.pk:
            return 'Unknown'

        orchestrator = PluginOrchestrator()
        success, runtime_status = orchestrator.get_container_status(obj.plugin_type, obj.plugin_uuid)
        if not success:
            return 'Unknown'

        return runtime_status.replace('_', ' ').title()

    def save_model(self, request, obj, form, change):
        """Saves, and sends the coordinates file if one came with the form.

        Launching and stopping are the actions: status is read-only here.
        """
        super().save_model(request, obj, form, change)

        upload = form.cleaned_data.get('coordinates_file') if form is not None else None
        if not upload:
            return
        try:
            lifecycle.send_coordinates_file(obj, upload)
        except lifecycle.LifecycleError as exc:
            self.message_user(request, f'Could not send the coordinates file to {obj.name}: {exc.detail}', level=messages.ERROR)
        else:
            self.message_user(request, f'Coordinates file sent to {obj.name}.', level=messages.SUCCESS)

    def delete_model(self, request, obj):
        try:
            lifecycle.delete(obj)
        except lifecycle.LifecycleError as exc:
            self.message_user(request, f'{obj.name} was not deleted: {exc.detail}', level=messages.ERROR)

    def delete_queryset(self, request, queryset):
        for plugin in queryset:
            self.delete_model(request, plugin)

    def _run(self, request, queryset, step, verb):
        done = 0
        for plugin in queryset:
            try:
                step(plugin)
            except lifecycle.LifecycleError as exc:
                self.message_user(request, f'Could not {verb} {plugin.name}: {exc.detail}', level=messages.ERROR)
            else:
                done += 1
        if done:
            self.message_user(request, f'{verb.capitalize()}: {done} plugin(s).', level=messages.SUCCESS)

    @admin.action(description='Launch selected plugins')
    def launch_selected_plugins(self, request, queryset):
        self._run(request, queryset, lifecycle.launch, 'launch')

    @admin.action(description='Stop selected plugins')
    def stop_selected_plugins(self, request, queryset):
        self._run(request, queryset, lifecycle.stop, 'stop')

    @admin.action(description='Sync selected plugin statuses from Docker')
    def sync_container_statuses(self, request, queryset):
        self._run(request, queryset, lifecycle.sync, 'sync')

@admin.register(Rotor)
class RotorAdmin(admin.ModelAdmin):
    list_display = ('device_id', 'name', 'online', 'min_elevation_deg', 'status_changed_at', 'last_state_at')
    list_filter = ('online',)
    search_fields = ('device_id', 'name')
    readonly_fields = ('device_id', 'online', 'status_changed_at', 'last_state_at', 'created_at')

    fieldsets = [
        (
            None,
            {'fields': ('device_id', 'name', 'online', 'status_changed_at', 'last_state_at', 'created_at')},
        ),
        (
            'Pointing limits',
            {
                'fields': ('min_elevation_deg', 'min_azimuth_deg', 'max_azimuth_deg'),
                'description': (
                    'The dispatcher cuts a trajectory and sends HOLD as soon as a point '
                    'falls outside these. Leave both azimuth fields empty for no azimuth '
                    'restriction; a start above the end wraps through north, e.g. 300 to 60. '
                    'The board keeps its own servo limits as the last line of defence.'
                ),
            },
        ),
        (
            'Location',
            {
                'fields': ('latitude_deg', 'longitude_deg', 'altitude_m'),
                'description': (
                    'Where the antenna stands. The plugins bound to this board compute '
                    'their passes for it; without latitude and longitude, tinygs computes none.'
                ),
            },
        ),
    ]

    def has_add_permission(self, request):
        # Boards are registered by a scan of the broker (POST /api/boards/scan).
        return False


@admin.register(RotorState)
class RotorStateAdmin(admin.ModelAdmin):
    list_display = (
        'received_at', 'rotor', 'mode', 'az_cdeg', 'el_cdeg', 'pan_mode',
        'batch_accepted', 'batch_error', 'latency_ms', 'clock_synced',
    )
    list_filter = ('rotor', 'mode', 'batch_accepted')

    # A history reported by the boards: nothing to add or edit by hand.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(DispatchOrder)
class DispatchOrderAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'rotor', 'plugin', 'kind', 'reason', 't0_ms', 't_end_ms', 't_sent_ms')
    list_filter = ('rotor', 'kind', 'reason')

    # What the dispatcher put on the wire: nothing to add or edit by hand.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
