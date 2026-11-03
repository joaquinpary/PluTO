import { notifications } from '@mantine/notifications';
import { errorMessage } from '../api/errors';

export function notifySuccess(message: string) {
  notifications.show({ color: 'green', message });
}

export function notifyError(error: unknown, title: string) {
  notifications.show({ color: 'red', title, message: errorMessage(error) });
}
