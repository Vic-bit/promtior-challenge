CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bookings (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users (id),
    room       TEXT NOT NULL CHECK (room IN ('A', 'B', 'C', 'D', 'E')),
    title      TEXT NOT NULL,
    attendees  INTEGER NOT NULL,
    start_time TIMESTAMPTZ NOT NULL,
    end_time   TIMESTAMPTZ NOT NULL,
    status     TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'cancelled')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS booking_slots (
    booking_id INTEGER NOT NULL REFERENCES bookings (id),
    room       TEXT NOT NULL,
    slot_start TIMESTAMPTZ NOT NULL,
    UNIQUE (room, slot_start)
);
