<?php
class TicketRepository
{
    public function all()
    {
        $rows = $this->rows(
            'SELECT t.id, t.title, t.status, s.name AS source_name
             FROM tickets t
             LEFT JOIN sources s ON s.id = t.source_id
             ORDER BY t.id'
        );
        foreach ($rows as &$row) {
            $row['id'] = (int) $row['id'];
        }
        return $rows;
    }

    public function find($id)
    {
        $row = pg_fetch_assoc(query(
            'SELECT t.id, t.title, t.description, t.status, t.updated_at,
                    s.id AS source_id, s.name AS source_name
             FROM tickets t
             LEFT JOIN sources s ON s.id = t.source_id
             WHERE t.id = $1',
            array($id)
        ));
        if (!$row) {
            return null;
        }
        return array(
            'id' => (int) $row['id'],
            'title' => $row['title'],
            'description' => $row['description'],
            'status' => $row['status'],
            'source' => $this->source($row),
            'updated_at' => $row['updated_at'],
        );
    }

    public function sources()
    {
        $rows = $this->rows('SELECT id, name FROM sources ORDER BY id');
        foreach ($rows as &$row) {
            $row['id'] = (int) $row['id'];
        }
        return $rows;
    }

    public function history($id)
    {
        $rows = $this->rows(
            'SELECT h.id, h.employee_id, e.name AS employee_name,
                    h.old_source_id, h.new_source_id, h.created_at
             FROM ticket_history h
             JOIN employees e ON e.id = h.employee_id
             WHERE h.ticket_id = $1
             ORDER BY h.id DESC',
            array($id)
        );
        foreach ($rows as &$row) {
            $row['id'] = (int) $row['id'];
            $row['employee_id'] = (int) $row['employee_id'];
            $row['old_source_id'] = $this->nullableInt($row['old_source_id']);
            $row['new_source_id'] = (int) $row['new_source_id'];
        }
        return $rows;
    }

    public function changeSource($id, $sourceId, array $employee)
    {
        $ticket = $this->requireEditableTicket($id);
        $this->requireKnownSource($sourceId);

        $oldSourceId = $this->nullableInt($ticket['source_id']);
        if ($oldSourceId === $sourceId) {
            return $this->find($id);
        }

        $this->storeSourceChange($id, $employee['id'], $oldSourceId, $sourceId);
        return $this->find($id);
    }

    private function requireEditableTicket($id)
    {
        $ticket = pg_fetch_assoc(query(
            'SELECT id, status, source_id FROM tickets WHERE id = $1',
            array($id)
        ));
        if (!$ticket) {
            respond(404, array(
                'error' => 'not_found',
                'message' => 'Заявка не найдена',
            ));
        }
        if ($ticket['status'] === 'archived') {
            respond(403, array(
                'error' => 'forbidden',
                'message' => 'Архивная заявка доступна только для чтения',
            ));
        }
        return $ticket;
    }

    private function requireKnownSource($sourceId)
    {
        if (!is_int($sourceId) || $sourceId <= 0) {
            respond(400, array(
                'error' => 'invalid_source',
                'message' => 'Выберите источник из справочника',
            ));
        }
        $source = pg_fetch_assoc(query(
            'SELECT id FROM sources WHERE id = $1',
            array($sourceId)
        ));
        if (!$source) {
            respond(400, array(
                'error' => 'invalid_source',
                'message' => 'Источник не найден',
            ));
        }
    }

    private function storeSourceChange($ticketId, $employeeId, $oldSourceId, $sourceId)
    {
        query('BEGIN');
        try {
            query(
                'UPDATE tickets
                 SET source_id = $1, updated_at = clock_timestamp()
                 WHERE id = $2',
                array($sourceId, $ticketId)
            );
            query(
                'INSERT INTO ticket_history
                    (ticket_id, employee_id, old_source_id, new_source_id)
                 VALUES ($1, $2, $3, $4)',
                array($ticketId, $employeeId, $oldSourceId, $sourceId)
            );
            query('COMMIT');
        } catch (Throwable $error) {
            @pg_query(db(), 'ROLLBACK');
            throw $error;
        }
    }

    private function rows($sql, array $params = array())
    {
        return pg_fetch_all(query($sql, $params)) ?: array();
    }

    private function source(array $row)
    {
        if ($row['source_id'] === null) {
            return null;
        }
        return array(
            'id' => (int) $row['source_id'],
            'name' => $row['source_name'],
        );
    }

    private function nullableInt($value)
    {
        return $value === null ? null : (int) $value;
    }
}
