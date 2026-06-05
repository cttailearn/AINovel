import { useEffect, useMemo, useState } from 'react';
import { EvidenceSection } from './EvidenceSection.jsx';

/**
 * Modal that displays detailed information for a character, event or
 * a single relation, including all attributes and connected entities.
 */
function renderAttrValue(value) {
  if (value === null || value === undefined || value === '') {
    return <span className="kg-detail-empty">—</span>;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="kg-detail-empty">—</span>;
    return (
      <div className="kg-detail-chips">
        {value.map((v, i) => (
          <span key={i} className="kg-detail-chip">{String(v)}</span>
        ))}
      </div>
    );
  }
  if (typeof value === 'object') {
    return (
      <pre className="kg-detail-json">
        {JSON.stringify(value, null, 2)}
      </pre>
    );
  }
  return <span className="kg-detail-val">{String(value)}</span>;
}

function AttributeList({ attributes }) {
  const entries = useMemo(() => {
    return Object.entries(attributes || {}).filter(
      ([, v]) => v !== null && v !== undefined && v !== '' &&
        !(Array.isArray(v) && v.length === 0)
    );
  }, [attributes]);
  if (entries.length === 0) {
    return <p className="kg-detail-no-attrs">该实体暂无附加属性信息。</p>;
  }
  return (
    <dl className="kg-detail-attrs">
      {entries.map(([k, v]) => (
        <div key={k} className="kg-detail-attr">
          <dt>{k}</dt>
          <dd>{renderAttrValue(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

function RelationsTable({ title, items, kind, entityMap, onJump }) {
  if (!items || items.length === 0) return null;
  return (
    <section className="kg-detail-section">
      <h4 className="kg-detail-section-title">
        {title} <span className="kg-detail-section-count">{items.length}</span>
      </h4>
      <ul className="kg-detail-rels">
        {items.map((r, i) => {
          const sourceName = entityMap[r.source] || r.source;
          const targetName = entityMap[r.target] || r.target;
          const isSource = r.source === entityMap._focusId;
          // Combine the legacy role/action shortcuts with the full
          // properties blob so user-added fields (时间, 地点, 情绪,
          // 动机, 亲疏程度, 关系状态, ...) show up here.
          const extraParts = [r.role, r.action].filter(Boolean);
          const extraProperties = r.properties
            ? Object.entries(r.properties)
                .filter(
                  ([k, v]) =>
                    v !== null && v !== undefined && v !== '' &&
                    !(Array.isArray(v) && v.length === 0) &&
                    k !== '角色' && k !== '具体行为' &&
                    k !== 'role' && k !== 'action'
                )
                .map(([k, v]) =>
                  `${k}: ${Array.isArray(v) ? v.join('、') : String(v)}`
                )
            : [];
          const extra = [...extraParts, ...extraProperties].join(' · ');
          return (
            <li
              key={`${kind}-${i}`}
              className={`kg-detail-rel ${isSource ? 'is-source' : 'is-target'}`}
            >
              <button
                type="button"
                className={`kg-detail-rel-side ${isSource ? 'is-self' : ''}`}
                onClick={() => !isSource && onJump?.(r.source)}
              >
                {sourceName}
              </button>
              <span className={`kg-detail-rel-tag kg-rel-${kind}`}>
                {r.relation}
              </span>
              <button
                type="button"
                className={`kg-detail-rel-side ${!isSource ? 'is-self' : ''}`}
                onClick={() => isSource && onJump?.(r.target)}
              >
                {targetName}
              </button>
              {extra && <span className="kg-detail-rel-extra">{extra}</span>}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

export function EntityDetailModal({
  open,
  onClose,
  data,
  // One of: { type: 'character' | 'event', entity: {...} } OR { type: 'relation', relation: {...} }
  selection,
  onSelectNode,
  // 点击 evidence 卡片时触发, 由父组件打开 EvidenceReader
  onJumpEvidence,
}) {
  // Hooks must be called unconditionally on every render — keep them
  // above any early return to satisfy the rules of hooks.
  const entityMap = useMemo(() => {
    const m = {};
    (data?.characters || []).forEach((c) => {
      if (c.entity_id) m[c.entity_id] = c.name;
    });
    (data?.events || []).forEach((e) => {
      if (e.entity_id) m[e.entity_id] = e.name;
    });
    return m;
  }, [data]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === 'Escape') onClose?.();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open || !selection) return null;

  const handleBackdrop = (e) => {
    if (e.target === e.currentTarget) onClose?.();
  };

  let body = null;
  if (selection.type === 'character' || selection.type === 'event') {
    const ent = selection.entity || {};
    const eid = ent.entity_id;
    const isCharacter = selection.type === 'character';
    const relationsFrom = isCharacter
      ? [
          ...(data?.character_event_relations || []).filter((r) => r.source === eid),
          ...(data?.character_relations || []).filter(
            (r) => r.source === eid || r.target === eid
          ),
        ]
      : [
          ...(data?.event_relations || []).filter(
            (r) => r.source === eid || r.target === eid
          ),
          ...(data?.character_event_relations || []).filter((r) => r.target === eid),
        ];
    entityMap._focusId = eid;
    const participations = isCharacter
      ? (data?.character_event_relations || []).filter((r) => r.source === eid)
      : (data?.character_event_relations || []).filter((r) => r.target === eid);
    const characterLinks = isCharacter
      ? (data?.character_relations || []).filter(
          (r) => r.source === eid || r.target === eid
        )
      : [];
    const eventLinks = isCharacter
      ? []
      : (data?.event_relations || []).filter(
          (r) => r.source === eid || r.target === eid
        );

    body = (
      <div className="kg-detail-body">
        <header className={`kg-detail-head ${isCharacter ? 'is-character' : 'is-event'}`}>
          <div className="kg-detail-avatar">
            {(ent.name || '?').slice(0, 1)}
          </div>
          <div className="kg-detail-titles">
            <h3>{ent.name || '未命名'}</h3>
            <div className="kg-detail-meta">
              <span className={`kg-detail-badge ${isCharacter ? 'is-character' : 'is-event'}`}>
                {isCharacter ? '人物' : '事件'}
              </span>
              <span className="kg-detail-id">ID: {eid || '—'}</span>
            </div>
          </div>
        </header>

        <section className="kg-detail-section">
          <h4 className="kg-detail-section-title">内在属性</h4>
          <AttributeList attributes={ent.attributes} />
        </section>

        <EvidenceSection
          extras={ent.extras}
          onJump={(ev) => onJumpEvidence?.({
            evidenceList: ent.extras?.evidence || [ev],
            jumpTo: ev,
            anchor: { type: isCharacter ? 'character' : 'event', entity: ent },
          })}
        />

        {isCharacter && (
          <RelationsTable
            title="参与事件"
            kind="ce"
            items={participations}
            entityMap={entityMap}
            onJump={(id) => {
              const ev = (data?.events || []).find((e) => e.entity_id === id);
              if (ev) onSelectNode?.({ type: 'event', entity: ev });
            }}
          />
        )}

        {isCharacter && (
          <RelationsTable
            title="人物间关系"
            kind="cc"
            items={characterLinks}
            entityMap={entityMap}
            onJump={(id) => {
              const c = (data?.characters || []).find((c) => c.entity_id === id);
              if (c) onSelectNode?.({ type: 'character', entity: c });
            }}
          />
        )}

        {!isCharacter && (
          <RelationsTable
            title="事件间关系"
            kind="ee"
            items={eventLinks}
            entityMap={entityMap}
            onJump={(id) => {
              const ev = (data?.events || []).find((e) => e.entity_id === id);
              if (ev) onSelectNode?.({ type: 'event', entity: ev });
            }}
          />
        )}

        {!isCharacter && (
          <RelationsTable
            title="参与该事件的人物"
            kind="ce"
            items={participations}
            entityMap={entityMap}
            onJump={(id) => {
              const c = (data?.characters || []).find((c) => c.entity_id === id);
              if (c) onSelectNode?.({ type: 'character', entity: c });
            }}
          />
        )}
      </div>
    );
  } else if (selection.type === 'relation') {
    const r = selection.relation || {};
    const sourceName = entityMap[r.source] || r.source;
    const targetName = entityMap[r.target] || r.target;
    // ``r.role``/``r.action`` are derived from ``r.properties`` for
    // participations; strip those keys so we don't render the same
    // value twice in 参与信息 and 附加属性.
    const allProperties = r.properties || {};
    const legacyShortcuts = new Set(
      ['角色', '具体行为', 'role', 'action'].filter(
        (k) => r[k] !== undefined && r[k] !== null && r[k] !== ''
      )
    );
    const extraProperties = Object.fromEntries(
      Object.entries(allProperties).filter(([k]) => !legacyShortcuts.has(k))
    );
    const hasShortcut = r.role || r.action;
    const hasExtraProperties = Object.keys(extraProperties).length > 0;
    body = (
      <div className="kg-detail-body">
        <header className="kg-detail-head is-relation">
          <div className="kg-detail-titles">
            <h3>关系详情</h3>
            <div className="kg-detail-meta">
              <span className="kg-detail-badge is-relation">{r.relation}</span>
            </div>
          </div>
        </header>
        <section className="kg-detail-section">
          <h4 className="kg-detail-section-title">连接</h4>
          <div className="kg-detail-relation-flow">
            <button
              type="button"
              className="kg-detail-rel-side"
              onClick={() => {
                const c = (data?.characters || []).find((c) => c.entity_id === r.source);
                if (c) onSelectNode?.({ type: 'character', entity: c });
                else {
                  const ev = (data?.events || []).find((e) => e.entity_id === r.source);
                  if (ev) onSelectNode?.({ type: 'event', entity: ev });
                }
              }}
            >
              {sourceName}
            </button>
            <span className="kg-detail-rel-tag kg-rel-arrow">{r.relation}</span>
            <button
              type="button"
              className="kg-detail-rel-side"
              onClick={() => {
                const c = (data?.characters || []).find((c) => c.entity_id === r.target);
                if (c) onSelectNode?.({ type: 'character', entity: c });
                else {
                  const ev = (data?.events || []).find((e) => e.entity_id === r.target);
                  if (ev) onSelectNode?.({ type: 'event', entity: ev });
                }
              }}
            >
              {targetName}
            </button>
          </div>
        </section>
        {hasShortcut && (
          <section className="kg-detail-section">
            <h4 className="kg-detail-section-title">参与信息</h4>
            <dl className="kg-detail-attrs">
              {r.role && (
                <div className="kg-detail-attr">
                  <dt>角色</dt>
                  <dd>{renderAttrValue(r.role)}</dd>
                </div>
              )}
              {r.action && (
                <div className="kg-detail-attr">
                  <dt>具体行为</dt>
                  <dd>{renderAttrValue(r.action)}</dd>
                </div>
              )}
            </dl>
          </section>
        )}
        {hasExtraProperties && (
          <section className="kg-detail-section">
            <h4 className="kg-detail-section-title">附加属性</h4>
            <AttributeList attributes={extraProperties} />
          </section>
        )}

        <EvidenceSection
          extras={r.extras}
          onJump={(ev) => onJumpEvidence?.({
            evidenceList: r.extras?.evidence || [ev],
            jumpTo: ev,
            anchor: { type: 'relation', relation: r },
          })}
        />
      </div>
    );
  }

  return (
    <div className="kg-detail-backdrop" onClick={handleBackdrop}>
      <div className="kg-detail-modal" role="dialog" aria-modal="true">
        <button
          type="button"
          className="kg-detail-close"
          onClick={onClose}
          aria-label="关闭"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
            <path d="M18 6L6 18M6 6l12 12" stroke="currentColor" strokeWidth="2" />
          </svg>
        </button>
        {body}
      </div>
    </div>
  );
}
