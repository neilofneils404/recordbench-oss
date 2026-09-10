PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS workbench_team_group (
    group_id TEXT PRIMARY KEY,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE CHECK(length(name) BETWEEN 1 AND 100),
    created_by TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workbench_team_group_member (
    group_id TEXT NOT NULL REFERENCES workbench_team_group(group_id) ON DELETE CASCADE,
    principal_id TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    granted_by TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    created_at TEXT NOT NULL,
    PRIMARY KEY(group_id, principal_id)
);
CREATE INDEX IF NOT EXISTS workbench_team_group_member_principal_idx
    ON workbench_team_group_member(principal_id, group_id);
CREATE TABLE IF NOT EXISTS workbench_matter_group_grant (
    matter_id TEXT NOT NULL REFERENCES workbench_matter(matter_id) ON DELETE CASCADE,
    group_id TEXT NOT NULL REFERENCES workbench_team_group(group_id) ON DELETE CASCADE,
    granted_by TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    created_at TEXT NOT NULL,
    PRIMARY KEY(matter_id, group_id)
);
CREATE INDEX IF NOT EXISTS workbench_matter_group_grant_group_idx
    ON workbench_matter_group_grant(group_id, matter_id);

-- One effective row per principal/matter. Direct grants keep their identity;
-- group-only access never acquires ownership or writes a direct grant.
CREATE VIEW IF NOT EXISTS workbench_effective_membership AS
SELECT d.matter_id,d.principal_id,d.role,d.state,d.granted_by,
       d.created_at,d.updated_at,d.revoked_at
FROM workbench_matter_membership d
JOIN workbench_principal p ON p.principal_id=d.principal_id
WHERE d.state='active' AND p.active=1
  AND recordbench_principal_enabled(p.provider,p.provider_subject)=1
UNION ALL
SELECT g.matter_id,m.principal_id,'member','active',g.granted_by,
       max(g.created_at,m.created_at),max(g.created_at,m.created_at),NULL
FROM workbench_matter_group_grant g
JOIN workbench_team_group_member m ON m.group_id=g.group_id
JOIN workbench_principal p ON p.principal_id=m.principal_id
WHERE p.active=1 AND recordbench_principal_enabled(p.provider,p.provider_subject)=1
  AND NOT EXISTS (
      SELECT 1 FROM workbench_matter_membership d
      WHERE d.matter_id=g.matter_id AND d.principal_id=m.principal_id AND d.state='active'
  )
  AND NOT EXISTS (
      SELECT 1 FROM workbench_matter_group_grant earlier
      JOIN workbench_team_group_member member ON member.group_id=earlier.group_id
      WHERE earlier.matter_id=g.matter_id AND member.principal_id=m.principal_id
        AND earlier.group_id<g.group_id
  );
