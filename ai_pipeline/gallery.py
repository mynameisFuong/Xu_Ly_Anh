"""Compile one current gallery per frame; compare faces using bounded matrix batches."""

import numpy as np


class CompiledGallery:
    def __init__(self, templates, dimension, *, metric="euclidean"):
        if metric not in {"euclidean", "cosine"}:
            raise ValueError("Unsupported distance metric")
        self.metric = metric
        self.dimension = dimension
        vectors, self.students, self.starts, self.owners = [], [], [], []
        for student_id, items in templates.items():
            valid = [np.asarray(item, np.float64) for item in items
                     if np.shape(item) == (dimension,) and np.isfinite(item).all()]
            if valid:
                self.starts.append(len(vectors))
                self.students.append(student_id)
                self.owners.extend([len(self.students) - 1] * len(valid))
                vectors.extend(valid)
        self.matrix = np.asarray(vectors, np.float64).reshape(-1, dimension)
        if metric == "cosine" and len(self.matrix):
            self.matrix = self.matrix / np.maximum(np.linalg.norm(self.matrix, axis=1, keepdims=True), 1e-12)

    def match_many(self, embeddings, *, threshold, margin):
        from ai_pipeline.recognition import MatchResult

        outcomes = []
        for offset in range(0, len(embeddings), 16):
            chunk = embeddings[offset:offset + 16]
            valid = [np.shape(item) == (self.dimension,) and np.isfinite(item).all() for item in chunk]
            probes = np.asarray([item if ok else np.zeros(self.dimension)
                                 for item, ok in zip(chunk, valid)], np.float64)
            if len(self.matrix):
                if self.metric == "cosine":
                    probes /= np.maximum(np.linalg.norm(probes, axis=1, keepdims=True), 1e-12)
                grouped = np.full((len(probes), len(self.students)),
                                   np.inf if self.metric == "euclidean" else -np.inf)
                for start in range(0, len(self.matrix), 512):
                    matrix = self.matrix[start:start + 512]
                    if self.metric == "euclidean":
                        # Bound temporary memory even for a large roster.
                        values = np.linalg.norm(probes[:, None, :] - matrix[None, :, :], axis=2)
                    else:
                        values = probes @ matrix.T
                    if len(self.matrix) <= 512:
                        grouped = (np.minimum if self.metric == "euclidean" else np.maximum).reduceat(
                            values, self.starts, axis=1)
                    else:
                        reduce = np.minimum if self.metric == "euclidean" else np.maximum
                        reduce.at(grouped, (np.arange(len(probes))[:, None],
                                            np.asarray(self.owners[start:start + 512])[None, :]), values)
            for index, ok in enumerate(valid):
                if not ok or not self.students:
                    outcomes.append(MatchResult(None, 0.0, 0.0, "unknown"))
                    continue
                row = grouped[index]
                order = np.argsort(row if self.metric == "euclidean" else -row, kind="stable")
                best = float(row[order[0]])
                second = float(row[order[1]]) if len(order) > 1 else (1.0 if self.metric == "euclidean" else 0.0)
                if self.metric == "euclidean":
                    accepted = best <= threshold and second - best >= margin
                    score, second_score = max(0.0, 1 - best), max(0.0, 1 - second)
                else:
                    accepted = best >= threshold and best - second >= margin
                    score, second_score = best, second
                outcomes.append(MatchResult(self.students[order[0]] if accepted else None, score, second_score,
                                            "recognized" if accepted else "low_confidence"))
        return outcomes
