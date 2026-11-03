"""Pagination of the history tables: states, dispatch orders and plugin data."""
from rest_framework.pagination import CursorPagination


class TimeCursorPagination(CursorPagination):
    """Newest first by the view's `time_field`, with a cursor instead of page numbers.

    The history tables grow by a row per second while a board tracks. A cursor
    makes every page "the next N before this instant" on the time index, where
    a page number would make the database count every row before it.
    """
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 1000

    def get_ordering(self, request, queryset, view):
        # The pk breaks ties between rows stored in the same instant.
        return (f'-{view.time_field}', '-pk')
