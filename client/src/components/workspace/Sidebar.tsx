import { useMemo, useRef, useState, type ChangeEvent, type DragEvent } from "react";
import { Link, NavLink, useNavigate, useParams } from "react-router-dom";

import {
  useCreateGroup,
  useCreateNote,
  useDeleteGroup,
  useDeleteNote,
  useGroups,
  useNotes,
  useProject,
  useUpdateGroup,
  useUpdateNote,
  useUploadMedia,
} from "../../api/hooks";
import type { Group, Note, NoteType } from "../../api/types";

interface TreeGroup extends Group {
  children: TreeGroup[];
  notes: Note[];
}

function buildTree(groups: Group[], notes: Note[]): { roots: TreeGroup[]; rootNotes: Note[] } {
  const byId = new Map<string, TreeGroup>();
  groups.forEach((g) => byId.set(g.id, { ...g, children: [], notes: [] }));

  const roots: TreeGroup[] = [];
  byId.forEach((g) => {
    const parent = g.parent_group_id ? byId.get(g.parent_group_id) : undefined;
    if (parent) parent.children.push(g);
    else roots.push(g);
  });

  const rootNotes: Note[] = [];
  notes.forEach((n) => {
    const group = n.group_id ? byId.get(n.group_id) : undefined;
    if (group) group.notes.push(n);
    else rootNotes.push(n);
  });

  const sortRec = (list: TreeGroup[]) => {
    list.sort((a, b) => a.name.localeCompare(b.name));
    for (const g of list) {
      sortRec(g.children);
      g.notes.sort((a, b) => a.title.localeCompare(b.title));
    }
  };
  sortRec(roots);
  rootNotes.sort((a, b) => a.title.localeCompare(b.title));

  return { roots, rootNotes };
}

function typeIcon(type: NoteType): string {
  if (type === "audio") return "🎙️";
  if (type === "video") return "🎬";
  if (type === "document") return "📄";
  return "📝";
}

const DOCUMENT_EXTENSIONS = [".pdf", ".docx", ".doc", ".txt", ".md"];

// Browsers don't always populate File.type for every recording container
// (e.g. some phone-recorded formats) or for less common document formats,
// so extension is checked as a fallback before defaulting to "audio" as the
// last-resort guess for anything unrecognized.
function inferType(file: File): Extract<NoteType, "audio" | "video" | "document"> {
  if (file.type.startsWith("video/")) return "video";
  if (file.type.startsWith("audio/")) return "audio";
  const name = file.name.toLowerCase();
  if (file.type === "application/pdf" || DOCUMENT_EXTENSIONS.some((ext) => name.endsWith(ext))) return "document";
  return "audio";
}

function stripExtension(filename: string): string {
  const idx = filename.lastIndexOf(".");
  return idx > 0 ? filename.slice(0, idx) : filename;
}

interface DragItem {
  kind: "note" | "group";
  id: string;
}

// null means "top level" (root). undefined means "nothing currently hovered".
type DropTarget = string | null | undefined;

function isValidDropTarget(item: DragItem, targetGroupId: string | null, groupsById: Map<string, Group>): boolean {
  if (item.kind === "note") return true; // notes are leaves -- any folder or root is fine
  if (targetGroupId === null) return true;
  if (targetGroupId === item.id) return false; // can't drop a folder into itself
  // Walk up from the target; if we hit the dragged group, the target is one
  // of its own descendants -- dropping there would create a cycle.
  let current: string | undefined = targetGroupId;
  while (current) {
    if (current === item.id) return false;
    current = groupsById.get(current)?.parent_group_id ?? undefined;
  }
  return true;
}

function isNoOpMove(item: DragItem, targetGroupId: string | null, groups: Group[], notes: Note[]): boolean {
  if (item.kind === "note") {
    const note = notes.find((n) => n.id === item.id);
    return note ? (note.group_id ?? null) === targetGroupId : true;
  }
  const group = groups.find((g) => g.id === item.id);
  return group ? (group.parent_group_id ?? null) === targetGroupId : true;
}

interface Actions {
  onNewNote: (groupId: string | null) => void;
  onUpload: (groupId: string | null) => void;
  onNewSubfolder: (groupId: string) => void;
  onDeleteGroup: (groupId: string, name: string) => void;
  onDeleteNote: (noteId: string) => void;
}

interface DragHandlers {
  dragItem: DragItem | null;
  dropTarget: DropTarget;
  onDragStart: (item: DragItem) => void;
  onDragEndItem: () => void;
  onDragOverTarget: (e: DragEvent, targetGroupId: string | null) => void;
  onDragLeaveTarget: (targetGroupId: string | null) => void;
  onDrop: (e: DragEvent, targetGroupId: string | null) => void;
}

export default function Sidebar({ projectId }: { projectId: string }) {
  const navigate = useNavigate();
  const { noteId: activeNoteId } = useParams<{ noteId: string }>();
  const { data: project } = useProject(projectId);
  const { data: groups } = useGroups(projectId);
  const { data: notes } = useNotes(projectId);

  const createGroup = useCreateGroup(projectId);
  const deleteGroup = useDeleteGroup(projectId);
  const updateGroup = useUpdateGroup(projectId);
  const createNote = useCreateNote(projectId);
  const deleteNote = useDeleteNote(projectId);
  const updateNote = useUpdateNote(projectId);
  const uploadMedia = useUploadMedia();

  const tree = useMemo(() => buildTree(groups ?? [], notes ?? []), [groups, notes]);
  const groupsById = useMemo(() => new Map((groups ?? []).map((g) => [g.id, g])), [groups]);

  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const pendingUploadGroupId = useRef<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [dragItem, setDragItem] = useState<DragItem | null>(null);
  const [dropTarget, setDropTarget] = useState<DropTarget>(undefined);

  function toggle(id: string) {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function handleNewNote(groupId: string | null) {
    const note = await createNote.mutateAsync({ title: "Untitled", type: "text", body: "", group_id: groupId });
    navigate(`/projects/${projectId}/notes/${note.id}`, { state: { focusTitle: true } });
  }

  function handleUpload(groupId: string | null) {
    pendingUploadGroupId.current = groupId;
    fileInputRef.current?.click();
  }

  async function handleFileChosen(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    const note = await createNote.mutateAsync({
      title: stripExtension(file.name),
      type: inferType(file),
      group_id: pendingUploadGroupId.current,
    });
    navigate(`/projects/${projectId}/notes/${note.id}`);
    uploadMedia.mutate({ noteId: note.id, file });
  }

  function handleNewSubfolder(parentId: string) {
    const name = window.prompt("Folder name:");
    if (name?.trim()) createGroup.mutate({ name: name.trim(), parent_group_id: parentId });
  }

  function handleNewRootFolder() {
    const name = window.prompt("Folder name:");
    if (name?.trim()) createGroup.mutate({ name: name.trim() });
  }

  function handleDeleteGroup(groupId: string, name: string) {
    if (confirm(`Delete folder "${name}"? Notes inside will move to the top level (not deleted).`)) {
      deleteGroup.mutate(groupId);
    }
  }

  function handleDeleteNote(noteId: string) {
    if (!confirm("Delete this note?")) return;
    deleteNote.mutate(noteId);
    if (noteId === activeNoteId) navigate(`/projects/${projectId}`);
  }

  const actions: Actions = {
    onNewNote: handleNewNote,
    onUpload: handleUpload,
    onNewSubfolder: handleNewSubfolder,
    onDeleteGroup: handleDeleteGroup,
    onDeleteNote: handleDeleteNote,
  };

  function performMove(item: DragItem, targetGroupId: string | null) {
    if (!isValidDropTarget(item, targetGroupId, groupsById)) return;
    if (isNoOpMove(item, targetGroupId, groups ?? [], notes ?? [])) return;
    if (item.kind === "note") {
      updateNote.mutate({ noteId: item.id, payload: { group_id: targetGroupId } });
    } else {
      updateGroup.mutate({ groupId: item.id, payload: { parent_group_id: targetGroupId } });
    }
  }

  const dragHandlers: DragHandlers = {
    dragItem,
    dropTarget,
    onDragStart: setDragItem,
    onDragEndItem: () => {
      setDragItem(null);
      setDropTarget(undefined);
    },
    onDragOverTarget: (e, targetGroupId) => {
      if (!dragItem || !isValidDropTarget(dragItem, targetGroupId, groupsById)) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      setDropTarget(targetGroupId);
    },
    onDragLeaveTarget: (targetGroupId) => {
      setDropTarget((current) => (current === targetGroupId ? undefined : current));
    },
    onDrop: (e, targetGroupId) => {
      e.preventDefault();
      e.stopPropagation();
      if (dragItem) performMove(dragItem, targetGroupId);
      setDragItem(null);
      setDropTarget(undefined);
    },
  };

  return (
    <>
      <input
        ref={fileInputRef}
        type="file"
        accept="audio/*,video/*,.pdf,.doc,.docx,.txt,.md"
        style={{ display: "none" }}
        onChange={handleFileChosen}
      />

      <Link to="/" className="sidebar-back">&larr; All projects</Link>
      <div className="sidebar-project-name" title={project?.name}>{project?.name ?? "…"}</div>

      <div className="sidebar-actions">
        <button className="icon-btn" title="New note" onClick={() => handleNewNote(null)}>📄+</button>
        <button className="icon-btn" title="Upload recording or document" onClick={() => handleUpload(null)}>📤</button>
        <button className="icon-btn" title="New folder" onClick={handleNewRootFolder}>📁+</button>
      </div>

      {dragItem && (
        <div
          className={`tree-root-dropzone${dropTarget === null ? " drop-target" : ""}`}
          onDragOver={(e) => dragHandlers.onDragOverTarget(e, null)}
          onDragLeave={() => dragHandlers.onDragLeaveTarget(null)}
          onDrop={(e) => dragHandlers.onDrop(e, null)}
        >
          Move to top level
        </div>
      )}

      <div className="sidebar-tree">
        {tree.roots.map((g) => (
          <FolderRow key={g.id} group={g} projectId={projectId} activeNoteId={activeNoteId} collapsed={collapsed} onToggle={toggle} actions={actions} drag={dragHandlers} />
        ))}
        {tree.rootNotes.map((n) => (
          <NoteRow key={n.id} note={n} projectId={projectId} active={n.id === activeNoteId} onDelete={actions.onDeleteNote} drag={dragHandlers} />
        ))}
        {tree.roots.length === 0 && tree.rootNotes.length === 0 && (
          <p className="tree-empty-hint">No notes yet — use the buttons above to create one.</p>
        )}
      </div>

      <div className="sidebar-footer">
        <NavLink to={`/projects/${projectId}/search`} className="sidebar-footer-link">🔍 Search</NavLink>
        <NavLink to={`/projects/${projectId}/graph`} className="sidebar-footer-link">🕸️ Keyword graph</NavLink>
        <NavLink to={`/projects/${projectId}/chat`} className="sidebar-footer-link">💬 Chat</NavLink>
      </div>
    </>
  );
}

function FolderRow({
  group,
  projectId,
  activeNoteId,
  collapsed,
  onToggle,
  actions,
  drag,
}: {
  group: TreeGroup;
  projectId: string;
  activeNoteId: string | undefined;
  collapsed: Set<string>;
  onToggle: (id: string) => void;
  actions: Actions;
  drag: DragHandlers;
}) {
  const isCollapsed = collapsed.has(group.id);
  const isDragging = drag.dragItem?.kind === "group" && drag.dragItem.id === group.id;
  const isDropTarget = drag.dropTarget === group.id;

  return (
    <div className="tree-node">
      <div
        className={`tree-row tree-folder${isDragging ? " dragging" : ""}${isDropTarget ? " drop-target" : ""}`}
        onClick={() => onToggle(group.id)}
        draggable
        onDragStart={(e) => {
          e.dataTransfer.effectAllowed = "move";
          e.dataTransfer.setData("text/plain", group.id);
          drag.onDragStart({ kind: "group", id: group.id });
        }}
        onDragEnd={drag.onDragEndItem}
        onDragOver={(e) => drag.onDragOverTarget(e, group.id)}
        onDragLeave={() => drag.onDragLeaveTarget(group.id)}
        onDrop={(e) => drag.onDrop(e, group.id)}
      >
        <span className="tree-chevron">{isCollapsed ? "▸" : "▾"}</span>
        <span className="tree-icon">📁</span>
        <span className="tree-label">{group.name}</span>
        <span className="tree-row-actions" onClick={(e) => e.stopPropagation()}>
          <button className="icon-btn" title="New note here" onClick={() => actions.onNewNote(group.id)}>📄+</button>
          <button className="icon-btn" title="Upload recording or document here" onClick={() => actions.onUpload(group.id)}>📤</button>
          <button className="icon-btn" title="New subfolder" onClick={() => actions.onNewSubfolder(group.id)}>📁+</button>
          <button className="icon-btn" title="Delete folder" onClick={() => actions.onDeleteGroup(group.id, group.name)}>✕</button>
        </span>
      </div>
      {!isCollapsed && (
        <div className="tree-children">
          {group.children.map((child) => (
            <FolderRow key={child.id} group={child} projectId={projectId} activeNoteId={activeNoteId} collapsed={collapsed} onToggle={onToggle} actions={actions} drag={drag} />
          ))}
          {group.notes.map((note) => (
            <NoteRow key={note.id} note={note} projectId={projectId} active={note.id === activeNoteId} onDelete={actions.onDeleteNote} drag={drag} />
          ))}
          {group.children.length === 0 && group.notes.length === 0 && <p className="tree-empty-hint">Empty</p>}
        </div>
      )}
    </div>
  );
}

function NoteRow({
  note,
  projectId,
  active,
  onDelete,
  drag,
}: {
  note: Note;
  projectId: string;
  active: boolean;
  onDelete: (noteId: string) => void;
  drag: DragHandlers;
}) {
  const isDragging = drag.dragItem?.kind === "note" && drag.dragItem.id === note.id;

  return (
    <div
      className={`tree-row tree-note${active ? " active" : ""}${isDragging ? " dragging" : ""}`}
      draggable
      onDragStart={(e) => {
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", note.id);
        drag.onDragStart({ kind: "note", id: note.id });
      }}
      onDragEnd={drag.onDragEndItem}
    >
      <Link to={`/projects/${projectId}/notes/${note.id}`} className="tree-row-link" draggable={false}>
        <span className="tree-icon">{typeIcon(note.type)}</span>
        <span className="tree-label">{note.title}</span>
        {(note.status === "pending" || note.status === "processing") && (
          <span className="tree-status-dot processing" title="Processing" />
        )}
        {note.status === "error" && <span className="tree-status-dot error" title="Error" />}
      </Link>
      <span className="tree-row-actions">
        <button className="icon-btn" title="Delete" onClick={() => onDelete(note.id)}>✕</button>
      </span>
    </div>
  );
}
