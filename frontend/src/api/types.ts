// Типы ответов API. Имена полей совпадают с JSON сервера (backend/app/services/*).

export type Role = "student" | "dean_staff" | "teacher" | "admin";

export interface User {
  id: number;
  username: string;
  role: Role;
  roleLabel: string;
  fullName: string;
  initials: string;
  isDemo: boolean;
  isGenerated: boolean;
  student: null | {
    faculty: { code: string; name: string };
    program: { code: string; name: string; degree: string };
    year: number;
    group: string;
    admissionYear: number;
    recordBook: string;
  };
  staff: null | { position: string; faculties: { code: string; name: string }[] };
}

export interface SubjectRef {
  id: number;
  name: string;
  shortName: string;
}

export interface LessonChange {
  type: "moved" | "room" | "cancelled";
  originalStartsAt: string;
  originalEndsAt: string;
  originalRoom: string;
  originalDate: string;
  timeChanged: boolean;
  roomChanged: boolean;
  dateChanged: boolean;
  reason: string | null;
  changedAt: string | null;
  summary: string;
}

export interface Lesson {
  id: number;
  courseId: number;
  subject: SubjectRef;
  kind: string;
  kindLabel: string;
  teacher: { id: number; name: string; shortName: string; title: string };
  room: string;
  date: string;
  startsAt: string;
  endsAt: string;
  pairNumber: number | null;
  status: "scheduled" | "moved" | "cancelled";
  change: LessonChange | null;
  minutesUntil?: number;
  minutesLeft?: number;
  isToday?: boolean;
}

export interface Deadline {
  id: number;
  kind: string;
  kindLabel: string;
  title: string;
  description: string | null;
  subject: SubjectRef | null;
  dueAt: string;
  date: string;
  hoursLeft: number;
  isSoon: boolean;
  isOverdue: boolean;
}

export type RequestStatus = "submitted" | "in_review" | "needs_info" | "approved" | "rejected";

export interface RequestStep {
  key: string;
  label: string;
  done: boolean;
}

export interface RequestSummary {
  id: number;
  number: string;
  type: string;
  typeTitle: string;
  title: string;
  status: RequestStatus;
  statusLabel: string;
  isFinal: boolean;
  createdAt: string;
  updatedAt: string;
  steps?: RequestStep[];
}

export interface RequestEvent {
  id: number;
  kind: "created" | "status" | "comment";
  fromStatus: RequestStatus | null;
  toStatus: RequestStatus | null;
  toStatusLabel: string | null;
  comment: string | null;
  actor: { role: string; label: string; isMe: boolean };
  createdAt: string;
}

export interface RequestDetail extends RequestSummary {
  description: string | null;
  eta: string | null;
  details: { key: string; label: string; value: string }[];
  comment: string | null;
  events: RequestEvent[];
  attachments: { id: number; name: string; mediaType: string; sizeBytes: number; createdAt: string }[];
  canComment: boolean;
  steps: RequestStep[];
}

export interface RequestField {
  key: string;
  label: string;
  kind: "select" | "number" | "date" | "text";
  required?: boolean;
  options?: { value: string; label: string }[];
  min?: number;
  max?: number;
  maxLength?: number;
  default?: string | number;
}

export interface RequestType {
  type: string;
  title: string;
  description: string;
  eta: string;
  commentRequired: boolean;
  fields: RequestField[];
}

export type NotificationLink =
  | { type: "lesson"; id: number; date: string }
  | { type: "request"; id: number }
  | { type: "announcement"; id: number }
  | { type: "deadline"; id: number; date: string }
  | { type: "grades"; courseId: number };

export interface Notification {
  id: number;
  kind: "lesson_change" | "announcement" | "deadline" | "request_status" | "grade";
  kindLabel: string;
  title: string;
  body: string;
  createdAt: string;
  read: boolean;
  link: NotificationLink | null;
  lesson?: Lesson;
}

export interface Dashboard {
  now: string;
  today: string;
  weekday: string;
  firstName: string;
  summary: {
    lessonsToday: number;
    lessonsLeftToday: number;
    changesToday: number;
    deadlinesSoon: number;
    unreadNotifications: number;
  };
  currentLesson: Lesson | null;
  nextLesson: Lesson | null;
  todayLessons: Lesson[];
  changes: Lesson[];
  deadlines: Deadline[];
  activeRequest: RequestSummary | null;
  notifications: Notification[];
}

export interface ScheduleDay {
  date: string;
  weekday: string;
  weekdayShort: string;
  isToday: boolean;
  lessons: Lesson[];
  movedAway: Lesson[];
}

export interface Schedule {
  from: string;
  to: string;
  today: string;
  days: ScheduleDay[];
  changes: Lesson[];
}

export interface GradeResult {
  type: "mark" | "credit";
  score: number;
  letter: string;
  mark?: number;
  passed: boolean;
  label: string;
}

export interface CourseGrades {
  courseId: number;
  subject: SubjectRef;
  teacher: { id: number; name: string; shortName: string; title: string };
  controlForm: "exam" | "credit" | "graded_credit";
  controlFormLabel: string;
  currentScore: number | null;
  currentLetter: string | null;
  atRisk: boolean;
  controls: {
    id: number;
    title: string;
    status: "graded" | "expected";
    score: number | null;
    maxScore: number;
    date: string | null;
    letter?: string;
  }[];
  final: {
    status: "graded" | "expected";
    result: GradeResult | null;
    retakes: number;
    date: string | null;
    startsAt: string | null;
    room: string | null;
  };
}

export interface TermGrades {
  id: number;
  title: string;
  isCurrent: boolean;
  courses: CourseGrades[];
  summary: {
    averageCurrentScore: number | null;
    averageFinalScore: number | null;
    coursesTotal: number;
    finalsDone: number;
    debts: string[];
    retaken: string[];
    atRisk: string[];
  };
  session: { title: string; state: "upcoming" | "in_progress" | "closed"; startsOn: string; endsOn: string };
}

export interface Grades {
  scale: { letter: string; min: number; max: number; mark: number; label: string }[];
  passThreshold: number;
  riskThreshold: number;
  currentTerm: TermGrades | null;
  pastTerms: TermGrades[];
  explanations: { currentScore: string; atRisk: string; expected: string };
}

export interface Announcement {
  id: number;
  title: string;
  body: string;
  publishedAt: string;
  audience: string;
  author: string;
}
