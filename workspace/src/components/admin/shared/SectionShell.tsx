import React, { useEffect } from 'react';
import { useAdminChat } from '../AdminChatContext';

interface Props {
  context: string;
  children: React.ReactNode;
}

/**
 * Wraps each admin section. Calls injectContext() whenever the section mounts
 * or its context string changes, so the AI panel always sees the current section's data.
 */
export default function SectionShell({ context, children }: Props) {
  const { injectContext } = useAdminChat();

  useEffect(() => {
    if (context) injectContext(context);
  }, [context, injectContext]);

  return <>{children}</>;
}
