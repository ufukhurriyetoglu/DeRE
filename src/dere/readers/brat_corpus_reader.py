import os
from itertools import product
from typing import Optional, Dict, List, Sequence, cast


from dere.corpus import Corpus, Instance
from dere.corpus import Span, Frame, Filler
from dere.readers import CorpusReader
from dere.taskspec import SpanType, FrameType


class BRATCorpusReader(CorpusReader):
    def load(self) -> Corpus:
        corpus = Corpus()
        self._populate_corpus(corpus)
        return corpus

    def _populate_corpus(self, corpus: Corpus) -> None:
        doc_id_list = list(
            {
                fname[:-3]
                for fname in os.listdir(self._corpus_path)
                if fname.endswith(".a1")
            }
        )
        for cur_id in doc_id_list:
            annotation2filename = str(self._corpus_path / (cur_id + ".a2"))
            # extend is O(n) in length of second list, not in length of both
            self.read_data(
                corpus=corpus,
                textfilename=str(self._corpus_path / (cur_id + ".txt")),
                doc_id=cur_id,
                annotation1filename=str(self._corpus_path / (cur_id + ".a1")),
                annotation2filename=annotation2filename,
            )

    def read_data(
        self,
        corpus: Corpus,
        textfilename: str,
        doc_id: str,
        annotation1filename: str,
        annotation2filename: Optional[str] = None,
    ) -> None:
        annotation_filenames = [annotation1filename]
        if annotation2filename is not None:
            annotation_filenames.append(annotation2filename)

        # construct our instances
        instances = []
        with open(textfilename) as f:
            end_offset = 0
            for line in f:
                start_offset = end_offset
                end_offset = start_offset + len(line)
                instance = Instance(line)
                instances.append((start_offset, end_offset, instance))
                corpus.instances.append(instance)

        # First pass -- construct our spans, and instantiate our frames
        spans = {}
        frames = {}
        for filename in annotation_filenames:
            with open(filename) as f:
                for line in f:
                    line = line.strip()
                    if line[0] == "T":  # Text spans
                        tag, type_left_right, span_string = line.split("\t")
                        span_type_name, sl, sr = type_left_right.split(" ")
                        s_left = int(sl)
                        s_right = int(sr)
                        span_type = self._spec.type_lookup("span:" + span_type_name)
                        if not isinstance(span_type, SpanType):
                            continue
                        for i_left, i_right, instance in instances:
                            if s_left >= i_left and s_right <= i_right:
                                span = Span(
                                    span_type,
                                    s_left - i_left,
                                    s_right - i_left,
                                    span_string,
                                )
                                assert (
                                    span_string == instance.text[span.left:span.right]
                                )
                                instance.spans.append(span)
                                spans[tag] = span
                                break

                    elif line[0] == "E":  # Events = frames
                        tag, *kvpairs = line.strip().split()
                        frame_type_name, _ = kvpairs[0].rsplit(":", 1)
                        frame_type = self._spec.type_lookup("frame:" + frame_type_name)
                        if type(frame_type) is not FrameType:
                            continue
                        frame_type = cast(FrameType, frame_type)
                        frames[tag] = Frame(frame_type)

        annotations: Dict[str, Filler] = {**spans, **frames}

        # second pass -- fill the slots for our frames
        for filename in annotation_filenames:
            with open(filename) as f:
                for line in f:
                    line = line.strip()
                    if line[0] == "E":
                        tag, *kvpairs = line.strip().split()
                        frame = frames[tag]
                        for kv in kvpairs:
                            slot_name, filler_tag = kv.rsplit(":", 1)
                            slot_type = frame.frame_type.slot_type_lookup(slot_name)
                            if slot_type is not None:
                                filler = annotations[filler_tag]
                                frame.slots[slot_type].add(filler)

        # add frames to our instances
        for instance in corpus.instances:
            instance.frames.extend(
                frames_referencing_spans(list(frames.values()), instance.spans)
            )


def frames_referencing_spans(
    frames: List[Frame], target_spans: List[Span]
) -> List[Frame]:
    connected_frames: List[Frame] = []
    updated = True
    while updated:
        updated = False
        # This is ugly, but mypy doesn't like + for different types
        target: List[Filler] = []
        target.extend(target_spans)
        target.extend(connected_frames)
        for frame in frames:
            if frame in connected_frames:
                continue
            for slot in frame.slots.values():
                for filler in slot.fillers:
                    if filler in target:
                        connected_frames.append(frame)
                        updated = True
    return list(connected_frames)
