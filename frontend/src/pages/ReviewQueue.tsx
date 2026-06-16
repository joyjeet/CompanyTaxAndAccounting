import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { useApi } from "../api/useApi";

/**
 * Reviewer dashboard. Lists all drafts pending review for the firm; clicking
 * one opens the detail page for promote / reject.
 */
export default function ReviewQueue() {
  const api = useApi();
  const drafts = useQuery({
    queryKey: ["drafts", "pending"],
    queryFn: () => api.listDrafts(true),
  });

  return (
    <div>
      <h2>Pending drafts</h2>
      {drafts.isLoading && <p>Loading…</p>}
      {drafts.error && <p className="error">{(drafts.error as Error).message}</p>}
      {drafts.data && drafts.data.length === 0 && (
        <p className="muted">No drafts awaiting review.</p>
      )}
      {drafts.data && drafts.data.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Kind</th>
              <th>Confidence</th>
              <th>Model</th>
              <th>Source doc</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {drafts.data.map((d) => {
              const conf = Number.parseFloat(d.confidence);
              const badge = d.high_confidence ? "high" : conf < 0.6 ? "low" : "";
              return (
                <tr key={d.id}>
                  <td>{d.kind}</td>
                  <td>
                    <span className={`badge ${badge}`}>{(conf * 100).toFixed(1)}%</span>
                  </td>
                  <td className="muted">{d.model}</td>
                  <td className="muted">{d.source_document_id.slice(0, 8)}…</td>
                  <td>
                    <Link to={`/drafts/${d.id}`}>Review</Link>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
