import { MantineProvider } from '@mantine/core';
import { render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import '../../../../i18n';
import { AnalysisMeta } from '../AnalysisMeta';

const meta = (props: Parameters<typeof AnalysisMeta>[0]) =>
  render(
    <MantineProvider>
      <AnalysisMeta {...props} />
    </MantineProvider>,
  );

it.each([
  [{ aiVerdict: null, aiChecked: true, profiled: true }, 'clean', 'done'],
  [{ aiVerdict: 'medium', aiChecked: true, profiled: false }, 'flagged', 'not yet'],
  [{ aiVerdict: null, aiChecked: false, profiled: undefined }, 'not yet', 'not yet'],
])('reads the AI check and the profile: %o', (props, ai, profile) => {
  meta(props);
  const [aiFlag, profileFlag] = screen.getAllByText(/:$/).map((el) => el.parentElement!);
  expect(aiFlag).toHaveTextContent(`AI check:${ai}`);
  expect(profileFlag).toHaveTextContent(`Profile:${profile}`);
});
