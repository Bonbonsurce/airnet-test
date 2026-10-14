import React, { useEffect, useRef, useState } from 'react';
import { api } from './api.js';

export default function TicketPanel({ employee, selectedId, sources, onChanged }) {
  const [ticket, setTicket] = useState(null);
  const [history, setHistory] = useState([]);
  const [sourceId, setSourceId] = useState('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const selectedIdRef = useRef(selectedId);
  selectedIdRef.current = selectedId;

  useEffect(() => {
    if (!selectedId) {
      setTicket(null);
      setHistory([]);
      setSourceId('');
      setLoading(false);
      setSaving(false);
      setError('');
      setMessage('');
      return;
    }
    let active = true;
    setLoading(true);
    setSaving(false);
    setError('');
    setMessage('');
    api(`/tickets/${selectedId}`).then(data => {
      if (!active) return;
      setTicket(data.ticket);
      setHistory(data.history);
      setSourceId(String(data.ticket.source?.id ?? ''));
    }).catch(error => {
      if (active) {
        setTicket(null);
        setHistory([]);
        setError(error.message);
      }
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [selectedId]);

  async function save() {
    if (!ticket || saving) return;
    const requestId = ticket.id;
    setSaving(true);
    setError('');
    setMessage('');
    try {
      const data = await api(`/tickets/${requestId}/source`, { method: 'POST', body: JSON.stringify({ source_id: Number(sourceId) }) });
      onChanged(data.ticket);
      if (selectedIdRef.current !== requestId) return;
      setTicket(data.ticket);
      setHistory(data.history);
      setSourceId(String(data.ticket.source?.id ?? ''));
      setMessage('Источник сохранён');
    } catch (error) {
      if (selectedIdRef.current !== requestId) return;
      setError(error.message);
    } finally {
      if (selectedIdRef.current === requestId) setSaving(false);
    }
  }

  const canEdit = employee.permissions.includes('FUNC_TICKETS_SOURCE_EDIT') && ticket?.status !== 'archived';
  const sourceName = id => sources.find(source => source.id === id)?.name ?? 'Не указан';
  const visibleTicket = ticket && ticket.id === selectedId ? ticket : null;

  return <section className="ticket-panel" aria-label="Карточка заявки">
    {!selectedId && <div className="empty"><h2>Выберите заявку</h2><p>Карточка и история изменений появятся здесь.</p></div>}
    {selectedId && loading && <p role="status" className="muted">Загрузка карточки…</p>}
    {error && <p className="error" role="alert">{error}</p>}
    {selectedId && !loading && visibleTicket && <>
      <div className="panel-heading"><span className="muted">Заявка #{visibleTicket.id}</span><h2>{visibleTicket.title}</h2><p>{visibleTicket.description}</p></div>
      <div className="source-box"><label htmlFor="source">Источник заявки</label>
        {canEdit ? <div className="source-controls"><select id="source" value={sourceId} onChange={event => setSourceId(event.target.value)} disabled={saving}><option value="" disabled>Выберите источник</option>{sources.map(source => <option key={source.id} value={source.id}>{source.name}</option>)}</select><button onClick={save} disabled={saving || !sourceId}>{saving ? 'Сохранение…' : 'Сохранить'}</button></div> : <p>{visibleTicket.source?.name ?? 'Не указан'}</p>}
        {visibleTicket.status === 'archived' && <p className="muted">Архивная заявка доступна только для чтения.</p>}
        {message && <p className="success" role="status">{message}</p>}
      </div>
      <div className="history"><h3>История изменения источника</h3>{history.length === 0 ? <p className="muted">Изменений пока нет.</p> : <ol>{history.map(item => <li key={item.id}><strong>{item.employee_name}</strong><p>{sourceName(item.old_source_id)} → {sourceName(item.new_source_id)}</p><time>{new Date(item.created_at).toLocaleString('ru-RU')}</time></li>)}</ol>}</div>
    </>}
  </section>;
}
