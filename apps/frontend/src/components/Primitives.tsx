import React from "react";
import { Loader2 } from "lucide-react";

export function Panel({
  id,
  title,
  icon,
  children,
  className
}: {
  id?: string;
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section id={id} className={`panel ${className ?? ""}`}>
      <div className="panel-header">
        <div className="panel-title">
          {icon}
          <h2>{title}</h2>
        </div>
      </div>
      {children}
    </section>
  );
}

export function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export function Table({ headers, rows }: { headers: string[]; rows: Array<Array<React.ReactNode>> }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {headers.map((header) => (
              <th key={header}>{header}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((cell, cellIndex) => (
                <td key={cellIndex}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function EmptyState({ icon, title, body }: { icon: React.ReactNode; title: string; body: string }) {
  return (
    <div className="empty-state">
      {icon}
      <h2>{title}</h2>
      <p>{body}</p>
    </div>
  );
}

export function EmptyInline({ text }: { text: string }) {
  return <div className="empty-inline">{text}</div>;
}

export function LoadingBlock({ label }: { label: string }) {
  return (
    <div className="loading">
      <Loader2 className="spin" size={18} />
      {label}
    </div>
  );
}
