import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/client';
import { renderWithProviders } from '../test/render';
import { server } from '../test/server';
import { CsvButton } from './CsvButton';

const downloadOrders = (kind?: 'BATCH' | 'HOLD') => () =>
  api.GET('/api/orders', { params: { query: { kind, format: 'csv' } }, parseAs: 'blob' });

describe('CsvButton', () => {
  afterEach(() => vi.restoreAllMocks());

  it('downloads the same query with format=csv', async () => {
    const urls: URL[] = [];
    server.use(
      http.get('/api/orders', ({ request }) => {
        urls.push(new URL(request.url));
        return new HttpResponse('id,kind\n1,HOLD\n', { headers: { 'Content-Type': 'text/csv' } });
      }),
    );
    const saved: string[] = [];
    URL.createObjectURL = vi.fn(() => 'blob:orders');
    URL.revokeObjectURL = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      saved.push(this.download);
    });
    const user = userEvent.setup();
    renderWithProviders(<CsvButton filename="ordenes.csv" download={downloadOrders('HOLD')} />);

    await user.click(screen.getByRole('button', { name: 'Exportar CSV' }));

    await waitFor(() => expect(saved).toEqual(['ordenes.csv']));
    expect(urls[0].searchParams.get('format')).toBe('csv');
    expect(urls[0].searchParams.get('kind')).toBe('HOLD');
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:orders');
  });

  it('tells the user when the export fails', async () => {
    server.use(http.get('/api/orders', () => HttpResponse.json({ detail: 'Too many rows.' }, { status: 400 })));
    const user = userEvent.setup();
    renderWithProviders(<CsvButton filename="ordenes.csv" download={downloadOrders()} />);

    await user.click(screen.getByRole('button', { name: 'Exportar CSV' }));

    expect(await screen.findByText('Too many rows.')).toBeInTheDocument();
  });
});
