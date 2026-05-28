from django.contrib import admin, messages

from .models import PluginInstance
from .orchestrator import PluginOrchestrator


@admin.register(PluginInstance)
class PluginInstanceAdmin(admin.ModelAdmin):
    actions = ['launch_selected_plugins', 'stop_selected_plugins', 'sync_container_statuses']
    list_display  = ('name', 'plugin_type', 'status', 'runtime_status', 'container_id', 'updated_at')
    list_filter   = ('plugin_type', 'status')
    search_fields = ('name', 'container_id')
    readonly_fields = ('runtime_status', 'container_id', 'created_at', 'updated_at')

    add_fieldsets = [
        (
            None,
            {'fields': ('name', 'plugin_type')},
        ),
        (
            'Ground Station',
            {'fields': ('station_lat', 'station_lon', 'station_alt')},
        ),
        (
            'Plugin Configuration',
            {
                'fields': ('config',),
                'description': (
                    'Plugin-specific parameters as a JSON object. '
                    'These are passed directly to the orchestrator when launching. '
                    'Example for file_tracker: '
                    '{"file_path": "/data/coords.txt", "coord_type": "ECEF", "coord_format": "GEO"}'
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
            'Ground Station',
            {'fields': ('station_lat', 'station_lon', 'station_alt')},
        ),
        (
            'Plugin Configuration',
            {
                'fields': ('config',),
                'description': (
                    'Plugin-specific parameters as a JSON object. '
                    'These are passed directly to the orchestrator when launching. '
                    'Example for file_tracker: '
                    '{"file_path": "/data/coords.txt", "coord_type": "ECEF", "coord_format": "GEO"}'
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
            readonly_fields.append('status')
        return tuple(readonly_fields)

    @staticmethod
    def _runtime_status_to_model_status(runtime_status):
        if runtime_status == 'running':
            return PluginInstance.Status.RUNNING
        if runtime_status == 'not_found':
            return PluginInstance.Status.STOPPED
        return PluginInstance.Status.ERROR

    @admin.display(description='Docker status')
    def runtime_status(self, obj):
        if not obj.pk:
            return 'Unknown'

        orchestrator = PluginOrchestrator()
        success, runtime_status = orchestrator.get_container_status(obj.plugin_type, obj.plugin_uuid)
        if not success:
            return 'Unknown'

        return runtime_status.replace('_', ' ').title()

    def _start_plugin(self, plugin, orchestrator):
        success, result = orchestrator.spawn_plugin(
            plugin_type=plugin.plugin_type,
            instance_id=plugin.plugin_uuid,
            station_coordinates=plugin.station_coordinates,
            **(plugin.config or {}),
        )

        if success:
            plugin.status = PluginInstance.Status.RUNNING
            plugin.container_id = result
            plugin.save(update_fields=['status', 'container_id', 'updated_at'])
            return True, result

        plugin.status = PluginInstance.Status.ERROR
        plugin.container_id = ''
        plugin.save(update_fields=['status', 'container_id', 'updated_at'])
        return False, result

    def _stop_plugin(self, plugin, orchestrator, failed_status=PluginInstance.Status.ERROR):
        success, result = orchestrator.kill_plugin(plugin.plugin_type, plugin.plugin_uuid)

        if success:
            plugin.status = PluginInstance.Status.STOPPED
            plugin.container_id = ''
            plugin.save(update_fields=['status', 'container_id', 'updated_at'])
            return True, result

        plugin.status = failed_status
        plugin.save(update_fields=['status', 'updated_at'])
        return False, result

    def _sync_plugin_status(self, plugin, orchestrator):
        success, runtime_status = orchestrator.get_container_status(plugin.plugin_type, plugin.plugin_uuid)
        if not success:
            return False, 'Could not query container status from Docker.'

        mapped_status = self._runtime_status_to_model_status(runtime_status)
        container_id = plugin.container_id

        if runtime_status == 'not_found':
            container_id = ''

        if plugin.status != mapped_status or plugin.container_id != container_id:
            plugin.status = mapped_status
            plugin.container_id = container_id
            plugin.save(update_fields=['status', 'container_id', 'updated_at'])

        return True, runtime_status

    def save_model(self, request, obj, form, change):
        previous_status = None
        if change:
            previous_status = PluginInstance.objects.get(pk=obj.pk).status

        super().save_model(request, obj, form, change)

        orchestrator = PluginOrchestrator()

        try:
            if not change and obj.status == PluginInstance.Status.RUNNING:
                success, result = self._start_plugin(obj, orchestrator)
                if not success:
                    self.message_user(request, f'Failed to launch {obj.name}: {result}', level=messages.ERROR)
                return

            if previous_status != PluginInstance.Status.RUNNING and obj.status == PluginInstance.Status.RUNNING:
                success, result = self._start_plugin(obj, orchestrator)
                if not success:
                    self.message_user(request, f'Failed to launch {obj.name}: {result}', level=messages.ERROR)
                return

            if previous_status == PluginInstance.Status.RUNNING and obj.status != PluginInstance.Status.RUNNING:
                success, result = self._stop_plugin(obj, orchestrator)
                if not success:
                    self.message_user(request, f'Failed to stop {obj.name}: {result}', level=messages.ERROR)
        except Exception as exc:
            obj.status = PluginInstance.Status.ERROR
            obj.save(update_fields=['status', 'updated_at'])
            self.message_user(request, f'Unexpected error while applying plugin lifecycle for {obj.name}: {exc}', level=messages.ERROR)

    def delete_model(self, request, obj):
        if obj.status == PluginInstance.Status.RUNNING:
            orchestrator = PluginOrchestrator()
            success, result = self._stop_plugin(obj, orchestrator, failed_status=PluginInstance.Status.RUNNING)
            if not success:
                self.message_user(request, f'Failed to stop {obj.name}. Deletion was cancelled: {result}', level=messages.ERROR)
                return

        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        orchestrator = PluginOrchestrator()
        deletable_ids = []

        for plugin in queryset:
            if plugin.status == PluginInstance.Status.RUNNING:
                success, result = self._stop_plugin(plugin, orchestrator, failed_status=PluginInstance.Status.RUNNING)
                if not success:
                    self.message_user(request, f'Failed to stop {plugin.name}. Deletion was cancelled: {result}', level=messages.ERROR)
                    continue

            deletable_ids.append(plugin.pk)

        if deletable_ids:
            super().delete_queryset(request, PluginInstance.objects.filter(pk__in=deletable_ids))

    @admin.action(description='Launch selected plugins')
    def launch_selected_plugins(self, request, queryset):
        orchestrator = PluginOrchestrator()
        launched = 0

        for plugin in queryset:
            if plugin.status == PluginInstance.Status.RUNNING:
                self.message_user(request, f'{plugin.name} is already running.', level=messages.WARNING)
                continue

            success, result = self._start_plugin(plugin, orchestrator)
            if success:
                launched += 1
            else:
                self.message_user(request, f'Failed to launch {plugin.name}: {result}', level=messages.ERROR)

        if launched:
            self.message_user(request, f'Launched {launched} plugin(s).', level=messages.SUCCESS)

    @admin.action(description='Stop selected plugins')
    def stop_selected_plugins(self, request, queryset):
        orchestrator = PluginOrchestrator()
        stopped = 0

        for plugin in queryset:
            if plugin.status != PluginInstance.Status.RUNNING:
                self.message_user(request, f'{plugin.name} is not running.', level=messages.WARNING)
                continue

            success, result = self._stop_plugin(plugin, orchestrator)
            if success:
                stopped += 1
            else:
                self.message_user(request, f'Failed to stop {plugin.name}: {result}', level=messages.ERROR)

        if stopped:
            self.message_user(request, f'Stopped {stopped} plugin(s).', level=messages.SUCCESS)

    @admin.action(description='Sync selected plugin statuses from Docker')
    def sync_container_statuses(self, request, queryset):
        orchestrator = PluginOrchestrator()
        synced = 0

        for plugin in queryset:
            success, result = self._sync_plugin_status(plugin, orchestrator)
            if success:
                synced += 1
            else:
                self.message_user(request, f'Failed to sync {plugin.name}: {result}', level=messages.ERROR)

        if synced:
            self.message_user(request, f'Synced {synced} plugin status value(s).', level=messages.SUCCESS)
