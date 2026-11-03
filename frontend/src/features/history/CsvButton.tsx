import { Button } from '@mantine/core';
import { useState } from 'react';
import { unwrap } from '../../shared/api/client';
import { notifyError } from '../../shared/lib/notify';

type CsvResult = { data?: Blob; error?: unknown; response: Response };

export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

interface Props {
  /** The table's request again, with format=csv and parseAs 'blob'. */
  download: () => Promise<CsvResult>;
  filename: string;
  disabled?: boolean;
}

/**
 * Downloads a history query as CSV (every row of the range). It goes
 * through the api client like any other call, so it carries the token and
 * shares its single refresh: a plain link could not send the Authorization header.
 */
export function CsvButton({ download, filename, disabled }: Props) {
  const [busy, setBusy] = useState(false);

  async function onClick() {
    setBusy(true);
    try {
      saveBlob(unwrap(await download()), filename);
    } catch (error) {
      notifyError(error, 'No se pudo exportar el CSV');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Button variant="default" onClick={onClick} loading={busy} disabled={disabled}>
      Exportar CSV
    </Button>
  );
}
