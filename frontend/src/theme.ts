import { Card, createTheme, NavLink, Paper, Table } from '@mantine/core';

export const theme = createTheme({
  primaryColor: 'indigo',
  defaultRadius: 'md',
  fontFamily: 'Inter, system-ui, -apple-system, "Segoe UI", Roboto, Ubuntu, sans-serif',
  headings: { fontWeight: '700' },
  components: {
    Card: Card.extend({ defaultProps: { withBorder: true, shadow: 'xs', radius: 'md' } }),
    Paper: Paper.extend({ defaultProps: { radius: 'md' } }),
    NavLink: NavLink.extend({
      styles: { root: { borderRadius: 'var(--mantine-radius-md)', marginBottom: 2 }, label: { fontWeight: 500 } },
    }),
    // Tables sit on the grey page, so they get the card background and a border.
    Table: Table.extend({
      defaultProps: { withTableBorder: true, verticalSpacing: 'sm' },
      styles: { table: { backgroundColor: 'var(--mantine-color-body)' } },
    }),
  },
});
