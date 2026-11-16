"""Pagination of the history tables."""
from rest_framework.pagination import CursorPagination


class TimeCursorPagination(CursorPagination):
    """Newest first by `time_field`; a cursor avoids counting rows on tables that grow every second."""
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 1000

    def get_ordering(self, request, queryset, view):
        # pk breaks same-instant ties.
        return (f'-{view.time_field}', '-pk')
