import type { ButtonHTMLAttributes, ReactNode } from 'react';

export function Button({ children, className = '', ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button className={`button ${className}`} {...props}>{children}</button>;
}

export function Toggle({ checked, onChange, label, disabled = false }: { checked: boolean; onChange: (value: boolean) => void; label?: string; disabled?: boolean }) {
  return <button type="button" aria-label={label} role="switch" aria-checked={checked} disabled={disabled} className={`toggle ${checked ? 'on' : ''}`} onClick={() => onChange(!checked)}><span /></button>;
}

export function StatusBadge({ value, tone = 'neutral' }: { value: string; tone?: 'good' | 'warn' | 'bad' | 'neutral' }) {
  return <span className={`status-badge ${tone}`}><i className="status-dot" />{value}</span>;
}

export function SectionHeader({ eyebrow, title, description, action }: { eyebrow?: string; title: string; description?: string; action?: ReactNode }) {
  return <div className="section-header"><div>{eyebrow && <small>{eyebrow}</small>}<h3>{title}</h3>{description && <p>{description}</p>}</div>{action}</div>;
}

export function EmptyState({ text, action }: { text: string; action?: ReactNode }) {
  return <div className="empty-state"><span>{text}</span>{action}</div>;
}

export function ErrorState({ text, onRetry }: { text: string; onRetry?: () => void }) {
  return <div className="inline-error"><span>{text}</span>{onRetry && <Button onClick={onRetry}>Retry</Button>}</div>;
}
