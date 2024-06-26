from langchain_openai import ChatOpenAI
import requests
from typing_extensions import TypedDict
from langchain_community.document_loaders import TextLoader
from langchain_community.vectorstores import Weaviate
from langchain.prompts import ChatPromptTemplate
from langchain.schema.runnable import RunnablePassthrough
from langchain.schema.output_parser import *
from datasets import Dataset
from ragas.metrics import (
    faithfulness,
    answer_relevancy,
    context_recall,
    context_precision,
    answer_correctness,
    answer_similarity
)
from langgraph.prebuilt import ToolNode
from langgraph.graph import END, MessageGraph, Graph, StateGraph
from ragas import evaluate
from langchain_core.runnables import RunnableLambda
from Vector_database import VectorDatabase
from Query_agent import *
from Feedback_system import FeedbackSystem


class RAGEval:
    """
    WorkFlow:
    1. Call RAGEval()
    2. Call ground_truth_prep()
    3. Call model_prep()
    4. Call query_agent_prep()
    5. Call feedback_prep()
    6. Call query()
    7. Call raga()
    """

    best = 2
    parse = StrOutputParser()

    def __init__(self, vb_list, cross_model):  # , q_model, q_parser, q_choice=1): # vb_list = [(vb,splitter)]
        self.cross_model = cross_model

        self.template = """You are an assistant for question-answering tasks.
        Use the following pieces of retrieved context to answer the question.
        If you don't know the answer, just say that you don't know.
        Else, answer as a human being would.
        Use two sentences maximum and keep the answer concise.
        Question: {question}
        Context: {context}
        Answer:
        """
        self.prompt = ChatPromptTemplate.from_template(self.template)
        self.vb_list = vb_list

    def ground_truths_prep(self, questions):  # questions is a file with questions
        self.ground_truths = [[s] for s in self.query(questions)]

    def model_prep(self, model, parser_choice=parse):  # model_link is the link to the model
        self.chat_model = model
        self.parser = parser_choice

    def query_agent_prep(self, model, parser):
        # self.query_agent = RunnableLambda(QueryAgent(self.vb_list, model,self.cross_model, parser).query)
        self.query_agent = RunnableLambda(AlternateQuestionAgent(self.vb_list, model, self.cross_model, parser).query)
        # self.query_agent = RunnableLambda(AugmentedQueryAgent(self.vb_list, model,self.cross_model,parser).query)

    def feedback_prep(self, file, embedding, url, api):
        self.fs = FeedbackSystem(file, embedding, url, api)
        self.rag_graph()

    def context_prep(self):
        con = self.query_agent.invoke(self.question).split('@@')
        uni_con = []
        for i in con:
            if i not in uni_con:
                uni_con.append(i)

        c = self.cross_model.rank(
            query=self.question,
            documents=uni_con,
            return_documents=True
        )[:self.best]
        self.context = str("\n".join([i['text'] for i in c]))  # str("\n".join(uni_con))

    def rag_chain(self):
        self.context_prep()
        context_agent = RunnableLambda(lambda x: self.context)
        self.ragchain = (
                {"context": context_agent, "question": RunnablePassthrough()}
                | self.prompt
                | self.chat_model
                | self.parser
        )

    def rag_graph(self):
        class GraphState(TypedDict):

            """
            Represents the state of our graph.

            Attributes:
                question: question
                context: context
                answer: answer
            """
            question: str
            context: str
            answer: str

        self.fs.feedback_retriever(top_k=1)

        def feedback(state):
            datas = self.fs.retriever.invoke(state["question"])
            data = (datas[0]).page_content
            print("Feedback retriver")
            print("/"*40)
            print(data)
            answer = data[data.find('and the response is') + len('and the response is'):]
            self.context = ""
            return {"question": state["question"], "context": "", "answer": answer}

        def feedback_check(state):  # state modifier
            datas = self.fs.retriever.invoke(state["question"])
            data = (datas[0]).page_content
            q = data[len('The feedback for'):]
            q = q[:q.find('and the response is')].strip()
            q = ((" ".join(q.split(' ')[:-3])).lower()).strip()
            print(q == (state["question"].lower()).strip())
            return "f_answer" if q == (state["question"].lower()).strip() else "fetch"

        def fetch(state):  # state modifier
            self.context_prep()
            return {"question": state["question"], "context": self.context, "answer": ""}

        def answer(state):  # state modifier
            chain = {"context": RunnableLambda(lambda x: self.context),
                     "question": RunnablePassthrough()} | self.prompt | self.chat_model | self.parser
            ans = chain.invoke(state["question"])
            return {"question": state["question"], "context": state["context"], "answer": ans}

        self.RAGraph = StateGraph(GraphState)
        self.RAGraph.set_entry_point("entry")
        self.RAGraph.add_node("entry", RunnablePassthrough())
        self.RAGraph.add_node("feedback", feedback)
        self.RAGraph.add_node("fetch", fetch)
        self.RAGraph.add_node("answerer", answer)
        self.RAGraph.add_edge("entry", "feedback")
        self.RAGraph.add_conditional_edges(
            "feedback",
            feedback_check,
            {"f_answer": END, "fetch": "fetch"}
        )
        self.RAGraph.add_edge("fetch", "answerer")
        self.RAGraph.add_edge("answerer", END)
        self.ragchain = self.RAGraph.compile()

    def query(self, question):
        self.question = question
        state = {"question": self.question, "context": "", "answer": ""}
        answer_state = self.ragchain.invoke(state)
        self.answer = answer_state["answer"]
        return self.answer

    def ragas(self):
        data = {
            "question": [self.question],
            "answer": [self.answer],
            "contexts": [[self.context]],
            "ground_truth": [self.ground_truth]
        }
        dataset = Dataset.from_dict(data)
        result = evaluate(
            dataset=dataset,
            metrics=[
                context_precision,
                context_recall,
                faithfulness,
                answer_relevancy
            ]
        )
        df = result.to_pandas()
        return df

# If making a custom Parser with init and invoke function, define it as follows
# parser = RunnableLambda(Parser().invoke)
# pass parser into the model_prep function
