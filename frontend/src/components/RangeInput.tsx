import { DatePickerInput } from '@mantine/dates';
import 'dayjs/locale/es';
import type { DateRange } from '../lib/history';

/** Days in local time; toRangeQuery() turns them into the UTC from/to of the API. */
export function RangeInput({ value, onChange, label = 'Fechas' }: { value: DateRange; onChange: (range: DateRange) => void; label?: string }) {
  return (
    <DatePickerInput
      type="range"
      label={label}
      value={value}
      onChange={onChange}
      locale="es"
      valueFormat="DD/MM/YYYY"
      allowSingleDateInRange
      maxDate={new Date()}
      miw={220}
    />
  );
}
