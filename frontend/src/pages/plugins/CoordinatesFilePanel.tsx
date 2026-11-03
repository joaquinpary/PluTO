import { Button, FileInput, Stack, Text } from '@mantine/core';
import { useState } from 'react';
import { useUploadCoordinates } from '../../api/queries';
import { ApiErrorAlert } from '../../components/ApiErrorAlert';
import { notifySuccess } from '../../lib/notify';

/** The server refuses more (MAX_FILE_BYTES in server_core/plugin_handlers/file_tracker.py). */
export const MAX_COORDINATES_BYTES = 1024 * 1024;

export function CoordinatesFilePanel({ uuid }: { uuid: string }) {
  const upload = useUploadCoordinates(uuid);
  const [file, setFile] = useState<File | null>(null);
  const [tooBig, setTooBig] = useState(false);

  function send() {
    if (!file) return;
    if (file.size > MAX_COORDINATES_BYTES) {
      setTooBig(true);
      return;
    }
    upload.mutate(file, { onSuccess: () => notifySuccess(`Se envió ${file.name}.`) });
  }

  return (
    <Stack maw={520}>
      <Text size="sm">
        Se le manda a la instancia esté en ejecución o no: si corre lo usa enseguida, y si no, cuando se lance. Un archivo
        nuevo reemplaza al anterior. Texto UTF-8, hasta 1 MiB.
      </Text>
      <FileInput
        label="Archivo"
        placeholder="Elegí un archivo de texto"
        value={file}
        onChange={(next) => {
          setFile(next);
          setTooBig(false);
        }}
        error={tooBig ? 'El archivo supera 1 MiB.' : undefined}
        clearable
      />
      <ApiErrorAlert error={upload.error} title="No se pudo enviar el archivo" />
      <Button onClick={send} disabled={!file} loading={upload.isPending} w="fit-content">
        Enviar archivo
      </Button>
    </Stack>
  );
}
