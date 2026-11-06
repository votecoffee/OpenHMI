import { useEffect, useState } from 'react';
import { api } from './api.mjs';

export function hasAlarmMessage(item) {
  return typeof item?.message === 'string' && (item.messages == null || (typeof item.messages === 'object'
    && !Array.isArray(item.messages) && Object.values(item.messages).every(message => typeof message === 'string')));
}

export function useAlarmRead(endpoint, validate, generation, identifier) {
  const [response, setResponse] = useState(null);
  useEffect(() => {
    if (!endpoint) return;
    let stopped = false, timer;
    async function refresh() {
      try {
        const data = await api(endpoint);
        if (!validate(data, identifier)) throw new Error('Invalid alarm response');
        if (!stopped) setResponse({ endpoint, data, receivedAt: new Date() });
      } catch (problem) {
        const discard = [401, 403, 404].includes(problem.status);
        if (!stopped) setResponse(previous => ({ ...(!discard && previous?.endpoint === endpoint ? previous : { endpoint }),
          error: problem.message }));
      }
      if (!stopped) timer = setTimeout(refresh, 1000);
    }
    refresh(); return () => { stopped = true; clearTimeout(timer); };
  }, [endpoint, validate, generation, identifier]);
  return response?.endpoint === endpoint ? response : {};
}
