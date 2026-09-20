-- ============================================================================
-- Royal Metal Allocation System — SQLite schema
-- Ported from Google Sheets (Apps Script build 5H)
--
-- DESIGN NOTE ON WEIGHTS — read before changing any numeric column.
--
-- SQLite has no exact decimal type. REAL is IEEE-754 binary floating point and
-- will drift; this system reconciles physical gold, so drift is a financial
-- error, not a rounding cosmetic.
--
-- Every weight is therefore stored as an INTEGER number of GRAMS.
-- The legacy system worked in kilograms to exactly 3 decimals, and 3 decimals
-- of a kilogram is precisely one gram, so the conversion is lossless:
--
--     kilograms = grams / 1000.0        (presentation only)
--     grams     = round(kilograms * 1000)
--
-- Convert at the application boundary, into Decimal, never float.
-- Column names carry the _g suffix so the unit is impossible to mistake.
--
-- DESIGN NOTE ON DATES
--
-- Dates are TEXT in strict 'YYYY-MM-DD' form — the same key format the legacy
-- DateService.gs produced. This sorts lexicographically, which means BETWEEN,
-- MAX() and ORDER BY all work directly, and is what makes back-dated carry-
-- forward lookups cheap. CHECK constraints reject any other shape.
-- The legacy STORAGE_HOUR = 12 hack is not needed: a date has no time.
-- ============================================================================

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;


-- ============================================================================
-- REFERENCE DATA — sourced from the "Metal Generator" sheet
-- ============================================================================

-- Parties own sectors. Both allocation sectors and flow sectors belong to one.
CREATE TABLE party (
    party_id        INTEGER PRIMARY KEY,
    party_name      TEXT    NOT NULL UNIQUE,
    party_key       TEXT    NOT NULL UNIQUE,   -- normalised: lowercase, no spaces/dashes
    is_active       INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);


-- Allocation sectors: legacy Metal Generator range A7:C25 plus the Party column.
-- Priority drives display order on the daily allocation screen.
CREATE TABLE sector (
    sector_id       INTEGER PRIMARY KEY,
    sector_name     TEXT    NOT NULL UNIQUE,
    sector_key      TEXT    NOT NULL UNIQUE,   -- normalised for matching
    priority        INTEGER NOT NULL,
    purity          TEXT    NOT NULL,          -- stored verbatim, e.g. '75%', '22K'
    party_id        INTEGER NOT NULL REFERENCES party(party_id),
    display_order   INTEGER,
    is_active       INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_sector_party    ON sector(party_id);
CREATE INDEX idx_sector_priority ON sector(priority);


-- Flow sectors: legacy Metal Generator range I7:I14, keyed by party.
-- A separate, smaller set from the allocation sectors — never merge the two.
CREATE TABLE flow_sector (
    flow_sector_id  INTEGER PRIMARY KEY,
    sector_name     TEXT    NOT NULL UNIQUE,
    sector_key      TEXT    NOT NULL UNIQUE,
    party_id        INTEGER NOT NULL REFERENCES party(party_id),
    display_order   INTEGER,
    is_active       INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_flow_sector_party ON flow_sector(party_id);


-- ============================================================================
-- IDENTITY AND SCOPE — from Config.gs ADMIN_EMAILS / OPERATOR_PARTIES /
-- OPERATOR_FLOW_SECTORS / NON_ADMIN_EMAILS
-- ============================================================================

CREATE TABLE app_user (
    user_id         INTEGER PRIMARY KEY,
    email           TEXT    NOT NULL UNIQUE,
    display_name    TEXT,
    is_admin        INTEGER NOT NULL DEFAULT 0 CHECK (is_admin IN (0, 1)),
    -- Mirrors the legacy NON_ADMIN_EMAILS deny list, which always wins.
    admin_denied    INTEGER NOT NULL DEFAULT 0 CHECK (admin_denied IN (0, 1)),
    is_active       INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- An operator may hold several parties.
CREATE TABLE user_party_scope (
    user_id         INTEGER NOT NULL REFERENCES app_user(user_id) ON DELETE CASCADE,
    party_id        INTEGER NOT NULL REFERENCES party(party_id)   ON DELETE CASCADE,
    PRIMARY KEY (user_id, party_id)
);

-- Explicit flow-sector grants. When absent, fall back to the sector's party.
CREATE TABLE user_flow_scope (
    user_id         INTEGER NOT NULL REFERENCES app_user(user_id)           ON DELETE CASCADE,
    flow_sector_id  INTEGER NOT NULL REFERENCES flow_sector(flow_sector_id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, flow_sector_id)
);


-- ============================================================================
-- METAL MASTER — the allocation ledger
-- Legacy headers: Date | Priority | Party | Sector | Purity |
--                 Previous Requirement | Today's Required Weight |
--                 Alloted | Balance
-- ============================================================================

CREATE TABLE metal_master (
    allocation_id           INTEGER PRIMARY KEY,
    allocation_date         TEXT    NOT NULL
        CHECK (allocation_date IS strftime('%Y-%m-%d', allocation_date)),

    sector_id               INTEGER NOT NULL REFERENCES sector(sector_id),
    party_id                INTEGER NOT NULL REFERENCES party(party_id),

    -- Denormalised snapshots. The sheet stored these on every row, and keeping
    -- them means a historical row still reports the priority and purity that
    -- applied ON THAT DATE, even after the sector definition is edited.
    priority_snapshot       INTEGER NOT NULL,
    purity_snapshot         TEXT    NOT NULL,

    previous_requirement_g  INTEGER NOT NULL DEFAULT 0,
    today_required_g        INTEGER NOT NULL DEFAULT 0,
    alloted_g               INTEGER NOT NULL DEFAULT 0,
    balance_g               INTEGER NOT NULL DEFAULT 0,

    revision_number         INTEGER NOT NULL DEFAULT 0,
    saved_by                TEXT    NOT NULL,
    saved_at                TEXT    NOT NULL DEFAULT (datetime('now')),

    -- One row per sector per date. A revision REPLACES the date's rows, exactly
    -- as deleteRowsForDate_() + appendBothMasters_() did on the sheet.
    UNIQUE (allocation_date, sector_id)
);

-- Primary lookup: "give me this date" and "give me the latest date before X".
CREATE INDEX idx_master_date        ON metal_master(allocation_date);
CREATE INDEX idx_master_date_party  ON metal_master(allocation_date, party_id);
CREATE INDEX idx_master_party_date  ON metal_master(party_id, allocation_date);
CREATE INDEX idx_master_sector_date ON metal_master(sector_id, allocation_date);


-- ============================================================================
-- METAL FLOW MASTER — the supply ledger
-- Legacy headers: Date | Party | Sector | Acquired
-- ============================================================================

CREATE TABLE metal_flow_master (
    flow_id             INTEGER PRIMARY KEY,
    allocation_date     TEXT    NOT NULL
        CHECK (allocation_date IS strftime('%Y-%m-%d', allocation_date)),

    flow_sector_id      INTEGER NOT NULL REFERENCES flow_sector(flow_sector_id),
    party_id            INTEGER NOT NULL REFERENCES party(party_id),

    acquired_g          INTEGER NOT NULL DEFAULT 0 CHECK (acquired_g >= 0),

    revision_number     INTEGER NOT NULL DEFAULT 0,
    saved_by            TEXT    NOT NULL,
    saved_at            TEXT    NOT NULL DEFAULT (datetime('now')),

    UNIQUE (allocation_date, flow_sector_id)
);

CREATE INDEX idx_flow_date       ON metal_flow_master(allocation_date);
CREATE INDEX idx_flow_date_party ON metal_flow_master(allocation_date, party_id);
CREATE INDEX idx_flow_party_date ON metal_flow_master(party_id, allocation_date);


-- ============================================================================
-- METAL ALLOCATION AUDIT LOG — append-only
-- Legacy headers: Audit_ID | Allocation_Date | Action_Type | Revision_Number |
--                 User_Email | Action_Timestamp | Revision_Reason |
--                 Previous_Allocation_Data | Updated_Allocation_Data |
--                 Previous_Metal_Flow_Data | Updated_Metal_Flow_Data |
--                 Request_ID | Action_Status
--
-- No UPDATE and no DELETE, ever. Enforced by trigger below.
-- ============================================================================

CREATE TABLE metal_allocation_audit_log (
    audit_row_id                INTEGER PRIMARY KEY,
    audit_id                    TEXT    NOT NULL UNIQUE,   -- 'AUD-20260818-104233-4821'

    allocation_date             TEXT    NOT NULL
        CHECK (allocation_date IS strftime('%Y-%m-%d', allocation_date)),

    action_type                 TEXT    NOT NULL CHECK (action_type IN (
                                    'SAVE', 'REVISE', 'BLOCKED_DUPLICATE',
                                    'FAILED_SAVE', 'FAILED_REVISION',
                                    'UNAUTHORIZED_REVISION')),
    action_status               TEXT    NOT NULL CHECK (action_status IN (
                                    'SUCCESS', 'BLOCKED', 'FAILED')),

    revision_number             INTEGER NOT NULL DEFAULT 0,
    user_email                  TEXT    NOT NULL,
    action_timestamp            TEXT    NOT NULL DEFAULT (datetime('now')),
    revision_reason             TEXT,

    -- Full before/after state as JSON. Kept verbatim so a revision can be
    -- replayed or diffed long after the sector definitions have changed.
    previous_allocation_data    TEXT,
    updated_allocation_data     TEXT,
    previous_metal_flow_data    TEXT,
    updated_metal_flow_data     TEXT,

    request_id                  TEXT
);

CREATE INDEX idx_audit_date      ON metal_allocation_audit_log(allocation_date);
CREATE INDEX idx_audit_timestamp ON metal_allocation_audit_log(action_timestamp);
CREATE INDEX idx_audit_user      ON metal_allocation_audit_log(user_email);
CREATE INDEX idx_audit_action    ON metal_allocation_audit_log(action_type);
CREATE INDEX idx_audit_request   ON metal_allocation_audit_log(request_id);

-- Append-only enforcement at the database level, not merely by convention.
CREATE TRIGGER trg_audit_no_update
BEFORE UPDATE ON metal_allocation_audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit log is append-only: UPDATE is not permitted');
END;

CREATE TRIGGER trg_audit_no_delete
BEFORE DELETE ON metal_allocation_audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit log is append-only: DELETE is not permitted');
END;


-- ============================================================================
-- STAGING — operator submissions awaiting admin commit
-- Legacy headers: Submission_ID | Allocation_Date | Party | Operator_Email |
--                 Submitted_At | Record_Type | Sector | Value | Status
-- ============================================================================

CREATE TABLE metal_requirement_staging (
    staging_id          INTEGER PRIMARY KEY,
    submission_id       TEXT    NOT NULL,

    allocation_date     TEXT    NOT NULL
        CHECK (allocation_date IS strftime('%Y-%m-%d', allocation_date)),

    party_id            INTEGER NOT NULL REFERENCES party(party_id),
    operator_email      TEXT    NOT NULL,
    submitted_at        TEXT    NOT NULL DEFAULT (datetime('now')),

    record_type         TEXT    NOT NULL CHECK (record_type IN ('ALLOCATION', 'FLOW')),

    -- Exactly one of these is set, according to record_type.
    sector_id           INTEGER REFERENCES sector(sector_id),
    flow_sector_id      INTEGER REFERENCES flow_sector(flow_sector_id),

    value_g             INTEGER NOT NULL DEFAULT 0,
    status              TEXT    NOT NULL DEFAULT 'PENDING',

    CHECK (
        (record_type = 'ALLOCATION' AND sector_id IS NOT NULL AND flow_sector_id IS NULL)
     OR (record_type = 'FLOW'       AND flow_sector_id IS NOT NULL AND sector_id IS NULL)
    )
);

CREATE INDEX idx_staging_date       ON metal_requirement_staging(allocation_date);
CREATE INDEX idx_staging_date_party ON metal_requirement_staging(allocation_date, party_id);
CREATE INDEX idx_staging_operator   ON metal_requirement_staging(operator_email);


-- ============================================================================
-- IDEMPOTENCY — replaces the legacy CacheService request-ID guard
-- (REQUEST_ID_TTL_SECONDS = 900). Prune rows older than the TTL on write.
-- ============================================================================

CREATE TABLE request_log (
    request_id      TEXT    PRIMARY KEY,
    user_email      TEXT    NOT NULL,
    endpoint        TEXT    NOT NULL,
    response_json   TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_request_created ON request_log(created_at);


-- ============================================================================
-- CONVENIENCE VIEWS — kilograms for presentation. Never compute on these.
-- ============================================================================

CREATE VIEW v_allocation_kg AS
SELECT
    m.allocation_id,
    m.allocation_date,
    s.sector_name,
    p.party_name,
    m.priority_snapshot                AS priority,
    m.purity_snapshot                  AS purity,
    m.previous_requirement_g / 1000.0  AS previous_requirement_kg,
    m.today_required_g       / 1000.0  AS today_required_kg,
    m.alloted_g              / 1000.0  AS alloted_kg,
    m.balance_g              / 1000.0  AS balance_kg,
    m.revision_number
FROM metal_master m
JOIN sector s ON s.sector_id = m.sector_id
JOIN party  p ON p.party_id  = m.party_id;


CREATE VIEW v_flow_kg AS
SELECT
    f.flow_id,
    f.allocation_date,
    fs.sector_name,
    p.party_name,
    f.acquired_g / 1000.0 AS acquired_kg,
    f.revision_number
FROM metal_flow_master f
JOIN flow_sector fs ON fs.flow_sector_id = f.flow_sector_id
JOIN party       p  ON p.party_id        = f.party_id;


-- Closing balance per date per party — the series behind the dashboard trend.
CREATE VIEW v_closing_balance_by_date AS
SELECT
    allocation_date,
    party_id,
    SUM(balance_g)           AS balance_g,
    SUM(balance_g) / 1000.0  AS balance_kg
FROM metal_master
GROUP BY allocation_date, party_id;
