BEGIN;

-- Running upgrade 0006 -> 0007

CREATE TABLE organization_invitations (
    id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    email VARCHAR(254) NOT NULL,
    role VARCHAR(20) NOT NULL,
    token_hash VARCHAR(64) NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    accepted_at TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (id),
    CHECK (role IN ('admin','member')),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE,
    UNIQUE (token_hash)
);

CREATE INDEX ix_organization_invitations_tenant_id ON organization_invitations (tenant_id);

CREATE TABLE organization_profiles (
    tenant_id UUID NOT NULL,
    slug VARCHAR(100) NOT NULL,
    status VARCHAR(20) DEFAULT 'pending' NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (tenant_id),
    CHECK (status IN ('active','pending','suspended')),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE,
    UNIQUE (slug)
);

CREATE TABLE audit_events (
    id UUID NOT NULL,
    actor_id UUID,
    tenant_id UUID,
    action VARCHAR(100) NOT NULL,
    target VARCHAR(100) DEFAULT '' NOT NULL,
    safe_metadata JSON DEFAULT '{}' NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(actor_id) REFERENCES users (id) ON DELETE SET NULL,
    FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

CREATE TABLE identity_tokens (
    id UUID NOT NULL,
    user_id UUID NOT NULL,
    purpose VARCHAR(30) NOT NULL,
    token_hash VARCHAR(64) NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    consumed_at TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (id),
    CHECK (purpose IN ('verify_email','password_reset')),
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE,
    UNIQUE (token_hash)
);

CREATE INDEX ix_identity_tokens_user_id ON identity_tokens (user_id);

CREATE TABLE organization_memberships (
    user_id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    role VARCHAR(20) DEFAULT 'member' NOT NULL,
    status VARCHAR(20) DEFAULT 'pending' NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (user_id, tenant_id),
    CHECK (role IN ('owner','admin','member')),
    CHECK (status IN ('active','pending','revoked')),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE platform_role_assignments (
    user_id UUID NOT NULL,
    role VARCHAR(30) DEFAULT 'super_admin' NOT NULL,
    granted_by UUID,
    granted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (user_id),
    CHECK (role = 'super_admin'),
    FOREIGN KEY(granted_by) REFERENCES users (id) ON DELETE SET NULL,
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE registration_requests (
    id UUID NOT NULL,
    user_id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    status VARCHAR(20) DEFAULT 'pending' NOT NULL,
    reviewed_by UUID,
    reviewed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CHECK (status IN ('pending','approved','rejected')),
    FOREIGN KEY(reviewed_by) REFERENCES users (id) ON DELETE SET NULL,
    FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_registration_requests_user_id ON registration_requests (user_id);

CREATE TABLE user_profiles (
    user_id UUID NOT NULL,
    name VARCHAR(200) DEFAULT '' NOT NULL,
    status VARCHAR(20) DEFAULT 'pending' NOT NULL,
    email_verified_at TIMESTAMP WITH TIME ZONE,
    legacy_access BOOLEAN DEFAULT 'false' NOT NULL,
    auth_version INTEGER DEFAULT '0' NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (user_id),
    CHECK (status IN ('active','pending','suspended')),
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

INSERT INTO user_profiles (user_id,name,status,legacy_access) SELECT id,'','active',true FROM users;

INSERT INTO organization_profiles (tenant_id,slug,status) SELECT id,'workspace-' || id::text,'active' FROM tenants;

INSERT INTO organization_memberships (user_id,tenant_id,role,status) SELECT id,tenant_id,'owner','active' FROM users;

UPDATE alembic_version SET version_num='0007' WHERE alembic_version.version_num = '0006';

COMMIT;
