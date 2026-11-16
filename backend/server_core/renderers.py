"""?format=csv for the history endpoints."""
import csv
import io
import json

from rest_framework.renderers import BaseRenderer


class CSVRenderer(BaseRenderer):
    media_type = 'text/csv'
    format = 'csv'
    charset = 'utf-8'

    def render(self, data, accepted_media_type=None, renderer_context=None):
        # Anything but {"results": [...]}, like an error, is one row.
        if isinstance(data, dict):
            rows = data['results'] if 'results' in data else [data]
        else:
            rows = data

        out = io.StringIO()
        writer = None
        for row in rows:
            if writer is None:
                writer = csv.DictWriter(out, fieldnames=list(row))
                writer.writeheader()
            # Nested values go as JSON.
            writer.writerow({
                key: json.dumps(value) if isinstance(value, (dict, list)) else value
                for key, value in row.items()
            })
        return out.getvalue()
