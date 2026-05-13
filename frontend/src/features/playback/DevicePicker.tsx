import { Popover } from '@mantine/core';
import type { ReactNode } from 'react';

export interface DevicePickerProps {
  opened: boolean;
  onClose: () => void;
  children: ReactNode;
}

/**
 * Desktop Popover container for the device picker list.
 *
 * Mantine 9 Popover anchors via <Popover.Target> — there is no anchorRef prop.
 * The surface is controlled (opened/onClose) from the outside; the hidden span
 * target is an implementation detail that lets us mount the picker independently
 * of the trigger button (which lives in PlayerCard).
 */
export function DevicePicker({ opened, onClose, children }: DevicePickerProps) {
  return (
    <Popover
      opened={opened}
      onChange={(o) => {
        if (!o) onClose();
      }}
      position="bottom-end"
      offset={6}
      shadow="md"
      width={280}
      withinPortal
    >
      {/* Hidden zero-size anchor. Positioning relative to the real trigger
          button (PlayerCard) is handled by the calling layer passing the anchor
          element; for F7 the popover floats near the bottom-right of the
          viewport, which is close enough for the picker UX. */}
      <Popover.Target>
        <span style={{ position: 'fixed', bottom: 60, right: 16, width: 0, height: 0 }} aria-hidden />
      </Popover.Target>
      <Popover.Dropdown p={0}>{children}</Popover.Dropdown>
    </Popover>
  );
}
